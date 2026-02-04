#!/bin/bash

# ============================================================
# 智能情感交互系统 - RedHat 7.9 + Oracle 一键部署脚本
# ============================================================
# 使用方法: bash INSTALL_DEPLOY_REDHAT_ORACLE.sh
# 支持系统: RedHat 7.9, CentOS 7.9, Oracle Linux 7.9
# 数据库: Oracle Database 11g/12c/19c
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
ORACLE_HOME="${ORACLE_HOME:-/u01/app/oracle/product/19c/dbhome_1}"
ORACLE_SID="${ORACLE_SID:-orcl}"
ORACLE_USER="${ORACLE_USER:-oracle}"
DB_USER="emotion_user"
DB_PASSWORD="emotion_password_123"  # 请修改此密码
DB_NAME="emotion_db"
APP_HOME="/opt/emotion_app"
NODE_VERSION="18"
PYTHON_VERSION="3.9"

# 打印函数
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# 检查是否为root用户
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "此脚本需要root权限运行"
        exit 1
    fi
    print_success "已验证root权限"
}

# 检查系统版本
check_system() {
    print_header "检查系统版本"
    
    if [ -f /etc/redhat-release ]; then
        OS_VERSION=$(cat /etc/redhat-release)
        print_success "检测到系统: $OS_VERSION"
    else
        print_error "不支持的操作系统"
        exit 1
    fi
}

# 更新系统
update_system() {
    print_header "更新系统包管理器"
    
    yum update -y
    yum groupinstall -y "Development Tools"
    print_success "系统更新完成"
}

# 安装基础工具
install_basic_tools() {
    print_header "安装基础工具"
    
    yum install -y \
        curl \
        wget \
        git \
        openssl-devel \
        libffi-devel \
        zlib-devel \
        bzip2-devel \
        readline-devel \
        sqlite-devel \
        ncurses-devel \
        gdbm-devel \
        db4-devel \
        libpcap-devel \
        xz-devel
    
    print_success "基础工具安装完成"
}

# 安装Node.js
install_nodejs() {
    print_header "安装Node.js"
    
    if command -v node &> /dev/null; then
        NODE_CURRENT=$(node -v)
        print_success "Node.js已安装: $NODE_CURRENT"
        return
    fi
    
    print_warning "Node.js未安装，正在安装..."
    
    # 使用NVM安装
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
    
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    
    nvm install $NODE_VERSION
    nvm use $NODE_VERSION
    nvm alias default $NODE_VERSION
    
    print_success "Node.js安装完成: $(node -v)"
}

# 安装pnpm
install_pnpm() {
    print_header "安装pnpm"
    
    if command -v pnpm &> /dev/null; then
        print_success "pnpm已安装: $(pnpm -v)"
        return
    fi
    
    npm install -g pnpm
    print_success "pnpm安装完成: $(pnpm -v)"
}

# 安装Python
install_python() {
    print_header "安装Python"
    
    if command -v python3 &> /dev/null; then
        PYTHON_CURRENT=$(python3 --version)
        print_success "Python已安装: $PYTHON_CURRENT"
        return
    fi
    
    print_warning "Python未安装，正在安装..."
    
    yum install -y python3 python3-devel python3-pip
    
    # 升级pip
    python3 -m pip install --upgrade pip
    
    print_success "Python安装完成: $(python3 --version)"
}

# 检查Oracle数据库
check_oracle() {
    print_header "检查Oracle数据库"
    
    if [ ! -d "$ORACLE_HOME" ]; then
        print_error "Oracle Home目录不存在: $ORACLE_HOME"
        print_warning "请确保Oracle数据库已安装"
        print_warning "如需安装Oracle，请参考: https://www.oracle.com/database/"
        return 1
    fi
    
    print_success "Oracle Home已找到: $ORACLE_HOME"
    
    # 检查Oracle客户端
    if ! command -v sqlplus &> /dev/null; then
        print_warning "sqlplus未在PATH中，尝试添加..."
        export PATH=$ORACLE_HOME/bin:$PATH
    fi
    
    print_success "Oracle数据库检查完成"
    return 0
}

# 创建Oracle数据库用户和表空间
create_oracle_user() {
    print_header "创建Oracle数据库用户"
    
    # 检查用户是否已存在
    if sqlplus -S / as sysdba << EOF | grep -q "^1"
set heading off feedback off pagesize 0 linesize 80 trimspool on
select count(*) from dba_users where username='${DB_USER^^}';
exit;
EOF
    then
        print_success "Oracle用户已存在: $DB_USER"
        return
    fi
    
    print_warning "创建新的Oracle用户: $DB_USER"
    
    sqlplus -S / as sysdba << EOF
create user $DB_USER identified by "$DB_PASSWORD";
grant connect, resource to $DB_USER;
grant unlimited tablespace to $DB_USER;
grant create table to $DB_USER;
grant create sequence to $DB_USER;
grant create procedure to $DB_USER;
exit;
EOF
    
    print_success "Oracle用户创建完成"
}

# 创建应用目录
create_app_directory() {
    print_header "创建应用目录"
    
    mkdir -p $APP_HOME
    cd $APP_HOME
    
    print_success "应用目录已创建: $APP_HOME"
}

# 解压项目文件
extract_project() {
    print_header "解压项目文件"
    
    if [ ! -f "emotion_app_complete_source.tar.gz" ]; then
        print_error "找不到 emotion_app_complete_source.tar.gz"
        print_warning "请将源码文件放在当前目录"
        exit 1
    fi
    
    tar -xzf emotion_app_complete_source.tar.gz
    print_success "项目文件解压完成"
}

# 安装前端依赖
install_frontend_deps() {
    print_header "安装前端依赖"
    
    if [ ! -f "package.json" ]; then
        print_error "找不到 package.json"
        exit 1
    fi
    
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    
    pnpm install
    print_success "前端依赖安装完成"
}

# 配置数据库连接
configure_database() {
    print_header "配置Oracle数据库连接"
    
    # 创建.env文件
    cat > .env << EOF
# Oracle数据库配置
DATABASE_URL="oracle://$DB_USER:$DB_PASSWORD@localhost:1521/$ORACLE_SID"

# JWT密钥
JWT_SECRET="your_jwt_secret_key_$(date +%s)"

# OAuth配置
VITE_APP_ID="your_app_id"
OAUTH_SERVER_URL="https://api.manus.im"
VITE_OAUTH_PORTAL_URL="https://portal.manus.im"

# 应用配置
VITE_APP_TITLE="智能情感交互系统"
VITE_APP_LOGO="/logo.png"

# 后端配置
BACKEND_PORT=5000
FRONTEND_PORT=3000

# Python后端配置
PYTHON_BACKEND_WS="ws://localhost:5000/ws/detect"

# 模型配置
MODEL_PATH="./models/best.onnx"
DEVICE="cpu"
EOF
    
    print_success "数据库配置文件已创建"
    print_warning "请修改.env文件中的敏感信息（密码、密钥等）"
}

# 初始化数据库
init_database() {
    print_header "初始化数据库"
    
    print_warning "注意: 当前使用Oracle数据库，需要手动创建表结构"
    print_warning "请参考 drizzle/schema.ts 中的表定义"
    
    # 提示用户
    echo ""
    echo "Oracle数据库初始化步骤:"
    echo "1. 使用SQLPlus连接到Oracle数据库"
    echo "2. 执行以下命令创建表:"
    echo ""
    echo "CREATE TABLE users ("
    echo "  id NUMBER PRIMARY KEY,"
    echo "  openId VARCHAR2(64) NOT NULL UNIQUE,"
    echo "  name VARCHAR2(255),"
    echo "  email VARCHAR2(320),"
    echo "  loginMethod VARCHAR2(64),"
    echo "  role VARCHAR2(20) DEFAULT 'user',"
    echo "  createdAt TIMESTAMP DEFAULT SYSDATE,"
    echo "  updatedAt TIMESTAMP DEFAULT SYSDATE,"
    echo "  lastSignedIn TIMESTAMP DEFAULT SYSDATE"
    echo ");"
    echo ""
    
    print_success "数据库初始化指南已显示"
}

# 安装后端依赖
install_backend_deps() {
    print_header "安装后端依赖"
    
    if [ ! -d "python-backend" ]; then
        print_error "找不到 python-backend 目录"
        exit 1
    fi
    
    cd python-backend
    
    # 创建虚拟环境
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        print_success "虚拟环境创建完成"
    fi
    
    # 激活虚拟环境
    source venv/bin/activate
    
    # 安装依赖
    pip install -r requirements.txt
    print_success "后端依赖安装完成"
    
    cd ..
}

# 创建启动脚本
create_startup_scripts() {
    print_header "创建启动脚本"
    
    # 前端启动脚本
    cat > start_frontend.sh << 'EOF'
#!/bin/bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
cd "$(dirname "$0")"
echo "启动前端应用..."
pnpm dev
EOF
    chmod +x start_frontend.sh
    print_success "前端启动脚本已创建"
    
    # 后端启动脚本
    cat > start_backend.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/python-backend"
source venv/bin/activate
echo "启动后端服务..."
python3 app.py
EOF
    chmod +x start_backend.sh
    print_success "后端启动脚本已创建"
    
    # 一键启动脚本
    cat > start_all.sh << 'EOF'
#!/bin/bash
echo "启动智能情感交互系统..."
echo ""
echo "1. 启动后端服务 (Python)..."
./start_backend.sh &
BACKEND_PID=$!
echo "后端服务PID: $BACKEND_PID"
sleep 3
echo ""
echo "2. 启动前端应用 (React)..."
./start_frontend.sh
EOF
    chmod +x start_all.sh
    print_success "一键启动脚本已创建"
}

# 创建Systemd服务文件
create_systemd_services() {
    print_header "创建Systemd服务文件"
    
    # 前端服务
    cat > /etc/systemd/system/emotion-frontend.service << EOF
[Unit]
Description=Emotion Interactive System Frontend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_HOME
ExecStart=$APP_HOME/start_frontend.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # 后端服务
    cat > /etc/systemd/system/emotion-backend.service << EOF
[Unit]
Description=Emotion Interactive System Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_HOME
ExecStart=$APP_HOME/start_backend.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    print_success "Systemd服务文件已创建"
    print_warning "使用以下命令启动服务:"
    echo "  systemctl start emotion-backend"
    echo "  systemctl start emotion-frontend"
}

# 显示部署信息
show_deployment_info() {
    print_header "部署完成！"
    
    echo ""
    echo -e "${GREEN}系统已准备就绪！${NC}"
    echo ""
    echo "📋 快速开始:"
    echo "  1. 修改.env文件中的敏感信息"
    echo "  2. 初始化Oracle数据库表结构"
    echo "  3. 启动后端服务:"
    echo "     ./start_backend.sh"
    echo ""
    echo "  4. 在另一个终端启动前端应用:"
    echo "     ./start_frontend.sh"
    echo ""
    echo "  5. 或使用Systemd服务启动:"
    echo "     systemctl start emotion-backend"
    echo "     systemctl start emotion-frontend"
    echo ""
    echo "🌐 访问应用:"
    echo "  前端应用: http://localhost:3000"
    echo "  后端服务: http://localhost:5000"
    echo ""
    echo "📚 文档:"
    echo "  - README_DEPLOYMENT.md - 部署指南"
    echo "  - DEPLOYMENT_COMPLETE_GUIDE.md - 详细配置说明"
    echo "  - python-backend/README.md - 后端说明"
    echo ""
    echo "⚠️  重要提示:"
    echo "  1. 请修改.env文件中的数据库密码和JWT密钥"
    echo "  2. 请创建Oracle数据库表结构（参考上面的SQL语句）"
    echo "  3. 确保Python后端和Node.js后端都已启动"
    echo ""
}

# 主函数
main() {
    print_header "智能情感交互系统 - RedHat 7.9 + Oracle 一键部署"
    
    check_root
    check_system
    update_system
    install_basic_tools
    install_nodejs
    install_pnpm
    install_python
    check_oracle
    create_oracle_user
    create_app_directory
    extract_project
    install_frontend_deps
    configure_database
    init_database
    install_backend_deps
    create_startup_scripts
    create_systemd_services
    show_deployment_info
}

# 运行主函数
main
