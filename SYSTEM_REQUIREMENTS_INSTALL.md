# 智能情感交互系统 - 系统依赖安装指南

## 📋 目录
1. [系统要求检查](#系统要求检查)
2. [Ubuntu/Debian 安装](#ubuntudebian-安装)
3. [CentOS/RHEL 安装](#centosrhel-安装)
4. [Windows 安装](#windows-安装)
5. [macOS 安装](#macos-安装)
6. [验证安装](#验证安装)

---

## 系统要求检查

### 硬件要求
```bash
# 检查CPU核心数
nproc

# 检查内存大小
free -h

# 检查硬盘空间
df -h /

# 检查系统架构
uname -m
```

**最低要求:**
- CPU: 2核
- 内存: 4GB
- 硬盘: 20GB
- 架构: x86_64 或 ARM64

### 系统版本检查
```bash
# 检查系统版本
cat /etc/os-release

# 或
lsb_release -a
```

---

## Ubuntu/Debian 安装

### 步骤1: 更新系统包管理器

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

### 步骤2: 安装基础工具

```bash
sudo apt-get install -y \
  curl \
  wget \
  git \
  build-essential \
  libssl-dev \
  libffi-dev \
  python3-dev
```

### 步骤3: 安装Node.js 18+

#### 方法A: 使用NVM（推荐）

```bash
# 下载并安装NVM
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# 刷新shell配置
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 安装Node.js 18
nvm install 18
nvm use 18
nvm alias default 18

# 验证安装
node -v
npm -v
```

#### 方法B: 使用NodeSource官方仓库

```bash
# 添加NodeSource仓库
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -

# 安装Node.js
sudo apt-get install -y nodejs

# 验证安装
node -v
npm -v
```

#### 方法C: 使用Snap

```bash
sudo snap install node --classic

# 验证安装
node -v
npm -v
```

### 步骤4: 安装pnpm

```bash
npm install -g pnpm

# 验证安装
pnpm -v
```

### 步骤5: 安装Python 3.8+

```bash
# 检查Python版本
python3 --version

# 如果版本低于3.8，安装新版本
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev

# 设置默认Python版本
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# 验证安装
python3 --version
```

### 步骤6: 安装pip和虚拟环境

```bash
sudo apt-get install -y python3-pip python3-venv

# 升级pip
python3 -m pip install --upgrade pip

# 验证安装
pip3 --version
```

### 步骤7: 安装MySQL 8.0

```bash
# 安装MySQL服务器和客户端
sudo apt-get install -y mysql-server mysql-client

# 运行安全配置脚本
sudo mysql_secure_installation

# 启动MySQL服务
sudo systemctl start mysql

# 设置开机自启
sudo systemctl enable mysql

# 验证安装
mysql --version
```

### 步骤8: 安装Git（如果需要）

```bash
sudo apt-get install -y git

# 配置Git
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# 验证安装
git --version
```

### 步骤9: 安装其他依赖

```bash
# 安装编译工具
sudo apt-get install -y gcc g++ make

# 安装图像处理库（用于YOLOv11）
sudo apt-get install -y libopencv-dev python3-opencv

# 安装系统库
sudo apt-get install -y libsm6 libxext6 libxrender-dev
```

---

## CentOS/RHEL 安装

### 步骤1: 更新系统包管理器

```bash
sudo yum update -y
sudo yum groupinstall -y "Development Tools"
```

### 步骤2: 安装基础工具

```bash
sudo yum install -y \
  curl \
  wget \
  git \
  openssl-devel \
  libffi-devel \
  python3-devel
```

### 步骤3: 安装Node.js 18+

#### 方法A: 使用NVM（推荐）

```bash
# 下载并安装NVM
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# 刷新shell配置
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 安装Node.js 18
nvm install 18
nvm use 18
nvm alias default 18

# 验证安装
node -v
npm -v
```

#### 方法B: 使用NodeSource官方仓库

```bash
# 添加NodeSource仓库
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -

# 安装Node.js
sudo yum install -y nodejs

# 验证安装
node -v
npm -v
```

### 步骤4: 安装pnpm

```bash
npm install -g pnpm

# 验证安装
pnpm -v
```

### 步骤5: 安装Python 3.8+

```bash
# 检查Python版本
python3 --version

# 安装Python 3.10
sudo yum install -y python3.10 python3.10-devel

# 设置默认Python版本
sudo alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# 验证安装
python3 --version
```

### 步骤6: 安装pip和虚拟环境

```bash
sudo yum install -y python3-pip

# 升级pip
python3 -m pip install --upgrade pip

# 验证安装
pip3 --version
```

### 步骤7: 安装MySQL 8.0

```bash
# 添加MySQL官方仓库
sudo yum install -y https://dev.mysql.com/get/mysql80-community-release-el7-1.noarch.rpm

# 安装MySQL
sudo yum install -y mysql-server

# 启动MySQL服务
sudo systemctl start mysqld

# 设置开机自启
sudo systemctl enable mysqld

# 获取临时密码
sudo grep 'temporary password' /var/log/mysqld.log

# 运行安全配置脚本
sudo mysql_secure_installation

# 验证安装
mysql --version
```

### 步骤8: 安装Git（如果需要）

```bash
sudo yum install -y git

# 配置Git
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# 验证安装
git --version
```

### 步骤9: 安装其他依赖

```bash
# 安装编译工具
sudo yum install -y gcc gcc-c++ make

# 安装图像处理库（用于YOLOv11）
sudo yum install -y opencv-devel python3-opencv

# 安装系统库
sudo yum install -y libSM libXext libXrender-devel
```

---

## Windows 安装

### 步骤1: 安装Node.js

1. 访问 https://nodejs.org/
2. 下载 LTS 版本（18.x 或更新）
3. 运行安装程序
4. 按照默认选项安装
5. 打开PowerShell或CMD验证：
```powershell
node -v
npm -v
```

### 步骤2: 安装pnpm

```powershell
npm install -g pnpm
pnpm -v
```

### 步骤3: 安装Python

1. 访问 https://www.python.org/downloads/
2. 下载 Python 3.10 或更新版本
3. 运行安装程序
4. **重要**: 勾选 "Add Python to PATH"
5. 打开PowerShell验证：
```powershell
python --version
pip --version
```

### 步骤4: 安装MySQL

1. 访问 https://dev.mysql.com/downloads/mysql/
2. 下载 MySQL 8.0 Community Server
3. 运行安装程序
4. 选择"Developer Default"安装类型
5. 配置MySQL服务
6. 打开CMD验证：
```cmd
mysql --version
```

### 步骤5: 安装Git（可选）

1. 访问 https://git-scm.com/download/win
2. 下载并运行安装程序
3. 按照默认选项安装
4. 打开PowerShell验证：
```powershell
git --version
```

### 步骤6: 安装Visual Studio Build Tools（可选但推荐）

```powershell
# 下载并安装
# https://visualstudio.microsoft.com/downloads/
# 选择 "Desktop development with C++"
```

---

## macOS 安装

### 步骤1: 安装Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 验证安装
brew --version
```

### 步骤2: 安装Node.js

#### 方法A: 使用Homebrew

```bash
brew install node@18

# 设置PATH
echo 'export PATH="/usr/local/opt/node@18/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 验证安装
node -v
npm -v
```

#### 方法B: 使用NVM

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

nvm install 18
nvm use 18
nvm alias default 18

# 验证安装
node -v
npm -v
```

### 步骤3: 安装pnpm

```bash
npm install -g pnpm

# 验证安装
pnpm -v
```

### 步骤4: 安装Python

```bash
# 使用Homebrew
brew install python@3.10

# 设置默认Python版本
echo 'export PATH="/usr/local/opt/python@3.10/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 验证安装
python3 --version
pip3 --version
```

### 步骤5: 安装MySQL

```bash
# 使用Homebrew
brew install mysql

# 启动MySQL服务
brew services start mysql

# 运行安全配置
mysql_secure_installation

# 验证安装
mysql --version
```

### 步骤6: 安装Git

```bash
brew install git

# 配置Git
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# 验证安装
git --version
```

### 步骤7: 安装其他依赖

```bash
# 安装OpenCV
brew install opencv

# 安装其他库
brew install libsm libxext libxrender
```

---

## 验证安装

### 创建验证脚本

创建文件 `verify_installation.sh`:

```bash
#!/bin/bash

echo "=========================================="
echo "系统依赖验证"
echo "=========================================="
echo ""

# 检查Node.js
echo "检查Node.js..."
if command -v node &> /dev/null; then
    echo "✓ Node.js: $(node -v)"
else
    echo "✗ Node.js: 未安装"
fi

# 检查npm
echo "检查npm..."
if command -v npm &> /dev/null; then
    echo "✓ npm: $(npm -v)"
else
    echo "✗ npm: 未安装"
fi

# 检查pnpm
echo "检查pnpm..."
if command -v pnpm &> /dev/null; then
    echo "✓ pnpm: $(pnpm -v)"
else
    echo "✗ pnpm: 未安装"
fi

# 检查Python
echo "检查Python..."
if command -v python3 &> /dev/null; then
    echo "✓ Python: $(python3 --version)"
else
    echo "✗ Python: 未安装"
fi

# 检查pip
echo "检查pip..."
if command -v pip3 &> /dev/null; then
    echo "✓ pip: $(pip3 --version)"
else
    echo "✗ pip: 未安装"
fi

# 检查MySQL
echo "检查MySQL..."
if command -v mysql &> /dev/null; then
    echo "✓ MySQL: $(mysql --version)"
else
    echo "✗ MySQL: 未安装"
fi

# 检查Git
echo "检查Git..."
if command -v git &> /dev/null; then
    echo "✓ Git: $(git --version)"
else
    echo "✗ Git: 未安装（可选）"
fi

# 检查系统资源
echo ""
echo "系统资源:"
echo "CPU核心数: $(nproc)"
echo "内存大小: $(free -h | grep Mem | awk '{print $2}')"
echo "硬盘空间: $(df -h / | tail -1 | awk '{print $4}')"

echo ""
echo "=========================================="
```

### 运行验证

```bash
bash verify_installation.sh
```

### 预期输出

```
==========================================
系统依赖验证
==========================================

检查Node.js...
✓ Node.js: v18.x.x
检查npm...
✓ npm: 9.x.x
检查pnpm...
✓ pnpm: 8.x.x
检查Python...
✓ Python: Python 3.10.x
检查pip...
✓ pip: pip 23.x.x from ...
检查MySQL...
✓ MySQL: mysql  Ver 8.0.x
检查Git...
✓ Git: git version 2.x.x

系统资源:
CPU核心数: 4
内存大小: 15Gi
硬盘空间: 100G

==========================================
```

---

## 常见问题

### Q1: Node.js版本过低怎么办？

```bash
# 使用NVM升级
nvm install 18
nvm use 18

# 或使用包管理器升级
sudo apt-get install --only-upgrade nodejs
```

### Q2: Python版本不对怎么办？

```bash
# 检查Python版本
python3 --version

# 如果版本低于3.8，安装新版本
sudo apt-get install python3.10

# 设置默认版本
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
```

### Q3: MySQL无法启动怎么办？

```bash
# 检查MySQL状态
sudo systemctl status mysql

# 启动MySQL
sudo systemctl start mysql

# 查看错误日志
sudo tail -f /var/log/mysql/error.log
```

### Q4: pnpm安装失败怎么办？

```bash
# 使用npm安装
npm install -g pnpm

# 或使用Homebrew（macOS）
brew install pnpm

# 或使用Yarn
npm install -g yarn
```

### Q5: 权限不足怎么办？

```bash
# 使用sudo运行
sudo npm install -g pnpm

# 或修改npm权限
mkdir ~/.npm-global
npm config set prefix '~/.npm-global'
export PATH=~/.npm-global/bin:$PATH
```

---

## 下一步

完成系统依赖安装后，按照以下步骤继续：

1. 查看 `QUICK_START_GUIDE.md` - 快速开始指南
2. 运行 `INSTALL_DEPLOY.sh` - 一键安装脚本
3. 启动应用并开始使用

---

## 获取帮助

如果遇到问题，请：

1. 检查日志文件
2. 查看 `DEPLOYMENT_COMPLETE_GUIDE.md` 的故障排除部分
3. 运行 `verify_installation.sh` 验证安装
4. 查看官方文档：
   - Node.js: https://nodejs.org/
   - Python: https://www.python.org/
   - MySQL: https://dev.mysql.com/
   - Git: https://git-scm.com/

---

**最后更新**: 2026年2月4日
