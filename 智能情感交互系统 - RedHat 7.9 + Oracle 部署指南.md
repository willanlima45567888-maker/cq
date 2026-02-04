# 智能情感交互系统 - RedHat 7.9 + Oracle 部署指南

## 📋 目录
1. [系统要求](#系统要求)
2. [快速开始](#快速开始)
3. [详细部署步骤](#详细部署步骤)
4. [Oracle数据库配置](#oracle数据库配置)
5. [故障排除](#故障排除)
6. [性能优化](#性能优化)

---

## 系统要求

### 硬件要求
- **CPU**: 2核或以上
- **内存**: 4GB 或以上
- **硬盘**: 30GB 或以上（包括Oracle数据库）
- **网络**: 稳定的网络连接

### 软件要求
- **操作系统**: RedHat Enterprise Linux 7.9 / CentOS 7.9 / Oracle Linux 7.9
- **Oracle数据库**: 11g / 12c / 19c / 21c
- **Node.js**: 18.0 或以上
- **Python**: 3.8 或以上
- **Git**: 2.0 或以上

---

## 快速开始

### 方法1: 一键部署脚本（推荐）

```bash
# 1. 下载部署脚本
chmod +x INSTALL_DEPLOY_REDHAT_ORACLE.sh

# 2. 运行部署脚本（需要root权限）
sudo bash INSTALL_DEPLOY_REDHAT_ORACLE.sh

# 3. 脚本会自动完成以下工作：
#    - 检查系统版本
#    - 安装基础工具
#    - 安装Node.js和Python
#    - 检查Oracle数据库
#    - 创建数据库用户
#    - 安装项目依赖
#    - 配置启动脚本
#    - 创建Systemd服务

# 4. 启动应用
systemctl start emotion-backend
systemctl start emotion-frontend

# 5. 访问应用
# 前端: http://localhost:3000
# 后端: http://localhost:5000
```

### 方法2: 手动部署

如果一键脚本失败或需要自定义配置，请按照下面的步骤手动部署。

---

## 详细部署步骤

### 步骤1: 系统准备

```bash
# 更新系统
sudo yum update -y

# 安装基础工具
sudo yum groupinstall -y "Development Tools"
sudo yum install -y curl wget git openssl-devel libffi-devel zlib-devel
```

### 步骤2: 安装Node.js

```bash
# 使用NVM安装Node.js
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# 重新加载shell配置
source ~/.bashrc

# 安装Node.js 18
nvm install 18
nvm use 18
nvm alias default 18

# 验证安装
node -v
npm -v
```

### 步骤3: 安装pnpm

```bash
# 全局安装pnpm
npm install -g pnpm

# 验证安装
pnpm -v
```

### 步骤4: 安装Python

```bash
# 安装Python 3
sudo yum install -y python3 python3-devel python3-pip

# 升级pip
python3 -m pip install --upgrade pip

# 验证安装
python3 --version
```

### 步骤5: 验证Oracle数据库

```bash
# 检查Oracle Home目录
echo $ORACLE_HOME

# 如果未设置，根据实际安装位置设置
export ORACLE_HOME=/u01/app/oracle/product/19c/dbhome_1
export PATH=$ORACLE_HOME/bin:$PATH

# 验证sqlplus
sqlplus -v
```

### 步骤6: 创建应用目录

```bash
# 创建应用目录
sudo mkdir -p /opt/emotion_app
cd /opt/emotion_app

# 解压源码
tar -xzf emotion_app_complete_source.tar.gz
cd emotion_system_showcase
```

### 步骤7: 安装前端依赖

```bash
# 安装依赖
pnpm install

# 验证安装
pnpm -v
```

### 步骤8: 配置数据库连接

```bash
# 创建.env文件
cat > .env << 'EOF'
# Oracle数据库配置
DATABASE_URL="oracle://emotion_user:emotion_password_123@localhost:1521/orcl"

# JWT密钥（使用强密钥）
JWT_SECRET="your_strong_jwt_secret_key_here"

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
```

### 步骤9: 初始化Oracle数据库

```bash
# 以Oracle用户身份连接数据库
sqlplus emotion_user/emotion_password_123@orcl

# 执行以下SQL创建表（在sqlplus中执行）
CREATE TABLE users (
  id NUMBER PRIMARY KEY,
  openId VARCHAR2(64) NOT NULL UNIQUE,
  name VARCHAR2(255),
  email VARCHAR2(320),
  loginMethod VARCHAR2(64),
  role VARCHAR2(20) DEFAULT 'user',
  createdAt TIMESTAMP DEFAULT SYSDATE,
  updatedAt TIMESTAMP DEFAULT SYSDATE,
  lastSignedIn TIMESTAMP DEFAULT SYSDATE
);

CREATE TABLE userSettings (
  id NUMBER PRIMARY KEY,
  userId NUMBER NOT NULL,
  voiceSpeed NUMBER DEFAULT 1.0,
  voiceVolume NUMBER DEFAULT 1.0,
  selectedVoice VARCHAR2(100) DEFAULT 'Google US English',
  autoResponse NUMBER DEFAULT 1,
  createdAt TIMESTAMP DEFAULT SYSDATE,
  updatedAt TIMESTAMP DEFAULT SYSDATE,
  FOREIGN KEY (userId) REFERENCES users(id)
);

CREATE TABLE emotionHistory (
  id NUMBER PRIMARY KEY,
  userId NUMBER NOT NULL,
  emotion VARCHAR2(50),
  confidence NUMBER,
  response VARCHAR2(500),
  aiResponse VARCHAR2(1000),
  createdAt TIMESTAMP DEFAULT SYSDATE,
  FOREIGN KEY (userId) REFERENCES users(id)
);

CREATE TABLE customResponses (
  id NUMBER PRIMARY KEY,
  userId NUMBER NOT NULL,
  emotion VARCHAR2(50),
  responseText VARCHAR2(500),
  createdAt TIMESTAMP DEFAULT SYSDATE,
  updatedAt TIMESTAMP DEFAULT SYSDATE,
  FOREIGN KEY (userId) REFERENCES users(id)
);

-- 创建序列用于自增ID
CREATE SEQUENCE users_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE userSettings_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE emotionHistory_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE customResponses_seq START WITH 1 INCREMENT BY 1;

-- 退出sqlplus
exit;
```

### 步骤10: 安装后端依赖

```bash
# 进入后端目录
cd python-backend

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 返回主目录
cd ..
```

### 步骤11: 创建启动脚本

```bash
# 创建后端启动脚本
cat > start_backend.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")/python-backend"
source venv/bin/activate
export PYTHONUNBUFFERED=1
python3 app.py
EOF
chmod +x start_backend.sh

# 创建前端启动脚本
cat > start_frontend.sh << 'EOF'
#!/bin/bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
cd "$(dirname "$0")"
pnpm dev
EOF
chmod +x start_frontend.sh

# 创建一键启动脚本
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
```

### 步骤12: 配置Systemd服务（可选）

```bash
# 创建后端服务文件
sudo tee /etc/systemd/system/emotion-backend.service > /dev/null << 'EOF'
[Unit]
Description=Emotion Interactive System Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/emotion_app/emotion_system_showcase
ExecStart=/opt/emotion_app/emotion_system_showcase/start_backend.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 创建前端服务文件
sudo tee /etc/systemd/system/emotion-frontend.service > /dev/null << 'EOF'
[Unit]
Description=Emotion Interactive System Frontend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/emotion_app/emotion_system_showcase
ExecStart=/opt/emotion_app/emotion_system_showcase/start_frontend.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 重新加载Systemd
sudo systemctl daemon-reload

# 启用服务开机自启
sudo systemctl enable emotion-backend
sudo systemctl enable emotion-frontend

# 启动服务
sudo systemctl start emotion-backend
sudo systemctl start emotion-frontend

# 查看服务状态
sudo systemctl status emotion-backend
sudo systemctl status emotion-frontend
```

---

## Oracle数据库配置

### 连接字符串格式

```
oracle://username:password@host:port/sid
```

### 常见的Oracle连接参数

| 参数 | 说明 | 示例 |
|------|------|------|
| username | 数据库用户名 | emotion_user |
| password | 数据库密码 | emotion_password_123 |
| host | 数据库主机地址 | localhost 或 192.168.1.100 |
| port | 数据库端口 | 1521 (默认) |
| sid | 数据库实例名 | orcl |

### 创建数据库用户

```sql
-- 以sysdba身份连接
sqlplus / as sysdba

-- 创建用户
CREATE USER emotion_user IDENTIFIED BY "emotion_password_123";

-- 授予权限
GRANT CONNECT, RESOURCE TO emotion_user;
GRANT UNLIMITED TABLESPACE TO emotion_user;
GRANT CREATE TABLE TO emotion_user;
GRANT CREATE SEQUENCE TO emotion_user;
GRANT CREATE PROCEDURE TO emotion_user;

-- 退出
EXIT;
```

### 导出/导入数据

```bash
# 导出数据库
expdp emotion_user/emotion_password_123@orcl DIRECTORY=data_pump_dir DUMPFILE=emotion_db.dmp

# 导入数据库
impdp emotion_user/emotion_password_123@orcl DIRECTORY=data_pump_dir DUMPFILE=emotion_db.dmp
```

---

## 故障排除

### 问题1: Node.js安装失败

**症状**: `command not found: node`

**解决方案**:
```bash
# 检查NVM是否正确安装
echo $NVM_DIR

# 重新加载shell配置
source ~/.bashrc

# 重新安装Node.js
nvm install 18
nvm use 18
```

### 问题2: Oracle连接失败

**症状**: `ORA-12514: TNS:listener does not currently know of service requested`

**解决方案**:
```bash
# 检查Oracle监听器状态
lsnrctl status

# 启动监听器
lsnrctl start

# 检查数据库实例
sqlplus / as sysdba
SELECT instance_name FROM v$instance;
EXIT;
```

### 问题3: Python依赖安装失败

**症状**: `error: Microsoft Visual C++ 14.0 is required`

**解决方案**:
```bash
# 安装开发工具
sudo yum groupinstall -y "Development Tools"

# 重新安装依赖
cd python-backend
source venv/bin/activate
pip install --upgrade setuptools wheel
pip install -r requirements.txt
```

### 问题4: 端口被占用

**症状**: `Address already in use`

**解决方案**:
```bash
# 查找占用端口的进程
lsof -i :3000
lsof -i :5000

# 杀死进程
kill -9 <PID>

# 或修改.env中的端口号
```

### 问题5: WebSocket连接失败

**症状**: `WebSocket连接错误`

**解决方案**:
```bash
# 检查后端服务是否运行
ps aux | grep python3

# 检查后端日志
tail -f python-backend/app.log

# 确保防火墙允许WebSocket连接
sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
```

---

## 性能优化

### 1. 数据库优化

```sql
-- 创建索引
CREATE INDEX idx_users_openId ON users(openId);
CREATE INDEX idx_emotionHistory_userId ON emotionHistory(userId);
CREATE INDEX idx_emotionHistory_createdAt ON emotionHistory(createdAt);

-- 统计信息
ANALYZE TABLE users;
ANALYZE TABLE emotionHistory;
```

### 2. Node.js优化

```bash
# 增加文件描述符限制
ulimit -n 65535

# 启用集群模式（可选）
# 修改package.json中的启动脚本
```

### 3. Python后端优化

```python
# 在app.py中启用多进程
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        workers=4,  # 根据CPU核心数调整
        threaded=True
    )
```

### 4. 系统级优化

```bash
# 增加文件描述符限制
sudo sysctl -w fs.file-max=2097152

# 增加TCP连接数
sudo sysctl -w net.core.somaxconn=65535

# 持久化配置
sudo tee -a /etc/sysctl.conf << EOF
fs.file-max=2097152
net.core.somaxconn=65535
EOF
sudo sysctl -p
```

---

## 常见命令

### 启动/停止服务

```bash
# 启动后端
systemctl start emotion-backend

# 启动前端
systemctl start emotion-frontend

# 停止服务
systemctl stop emotion-backend
systemctl stop emotion-frontend

# 重启服务
systemctl restart emotion-backend
systemctl restart emotion-frontend

# 查看状态
systemctl status emotion-backend
systemctl status emotion-frontend

# 查看日志
journalctl -u emotion-backend -f
journalctl -u emotion-frontend -f
```

### 数据库操作

```bash
# 连接数据库
sqlplus emotion_user/emotion_password_123@orcl

# 查看表结构
DESC users;

# 查看数据
SELECT * FROM users;

# 备份数据库
expdp emotion_user/emotion_password_123@orcl DIRECTORY=data_pump_dir DUMPFILE=backup_$(date +%Y%m%d).dmp
```

---

## 安全建议

1. **修改默认密码** - 更改Oracle用户和应用密码
2. **启用SSL/TLS** - 配置HTTPS和安全WebSocket（WSS）
3. **防火墙配置** - 只开放必要的端口
4. **定期备份** - 定期备份Oracle数据库
5. **监控日志** - 定期检查应用和数据库日志

---

## 支持和反馈

如遇到问题，请检查以下文件：
- `README_DEPLOYMENT.md` - 基础部署指南
- `DEPLOYMENT_COMPLETE_GUIDE.md` - 详细配置说明
- `python-backend/README.md` - 后端说明
- `SYSTEM_REQUIREMENTS_INSTALL.md` - 系统依赖安装

---

**最后更新**: 2026年2月4日
**版本**: 1.0.0
