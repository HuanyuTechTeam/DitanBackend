# Docker 构建和运行脚本 (PowerShell 版本)
# 用于 Windows 系统快速构建和启动 DitanBackend 服务

param(
    [Parameter(Position=0)]
    [string]$Command = "help",
    
    [Parameter(Position=1)]
    [string]$Option = ""
)

# 颜色定义
$script:InfoColor = "Cyan"
$script:SuccessColor = "Green"
$script:WarningColor = "Yellow"
$script:ErrorColor = "Red"

# 打印带颜色的消息
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor $script:InfoColor
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor $script:SuccessColor
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor $script:WarningColor
}

function Write-Error-Msg {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor $script:ErrorColor
}

# 显示使用说明
function Show-Help {
    @"
DitanBackend Docker 管理脚本 (Windows 版本)

使用方式:
    .\docker_build.ps1 [命令] [选项]

命令:
    build       构建本地开发镜像
    up          启动服务（构建并运行）
    down        停止服务
    restart     重启服务
    logs        查看日志
    ps          查看运行状态
    clean       清理容器和镜像
    dev         启动开发环境
    prod        启动生产环境
    init        初始化环境（创建 .env 文件）
    help        显示此帮助信息

选项:
    -f, --follow    跟踪日志输出（用于 logs 命令）

示例:
    .\docker_build.ps1 build        # 构建镜像
    .\docker_build.ps1 up           # 启动服务
    .\docker_build.ps1 logs -f      # 实时查看日志
    .\docker_build.ps1 down         # 停止服务
    .\docker_build.ps1 dev          # 启动开发环境
    .\docker_build.ps1 clean        # 清理环境

"@
}

# 检查 Docker 是否安装
function Test-Docker {
    try {
        $null = Get-Command docker -ErrorAction Stop
        $null = Get-Command docker-compose -ErrorAction Stop
        Write-Success "Docker 环境检查通过"
        return $true
    }
    catch {
        Write-Error-Msg "Docker 或 Docker Compose 未安装，请先安装"
        return $false
    }
}

# 初始化环境
function Initialize-Environment {
    Write-Info "初始化环境..."
    
    if (-not (Test-Path .env)) {
        if (Test-Path .env.example) {
            Copy-Item .env.example .env
            Write-Success "已创建 .env 文件，请根据实际情况修改配置"
            Write-Warning "请修改 .env 文件中的 DATABASE_PASSWORD"
        }
        else {
            Write-Error-Msg ".env.example 文件不存在"
            exit 1
        }
    }
    else {
        Write-Info ".env 文件已存在，跳过创建"
    }
    
    # 创建日志目录
    if (-not (Test-Path logs)) {
        New-Item -ItemType Directory -Path logs | Out-Null
        Write-Success "日志目录已创建"
    }
}

# 构建镜像
function Build-Image {
    Write-Info "开始构建本地开发镜像..."
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml build app
    if ($LASTEXITCODE -eq 0) {
        Write-Success "本地开发镜像构建完成"
    }
    else {
        Write-Error-Msg "镜像构建失败"
        exit 1
    }
}

# 启动服务
function Start-Services {
    Write-Info "启动服务..."
    docker-compose up -d
    if ($LASTEXITCODE -eq 0) {
        Write-Success "服务已在后台启动"
        Write-Info "访问 http://localhost:8000 查看服务"
        Write-Info "访问 http://localhost:8000/docs 查看 API 文档"
        Write-Info "使用 '.\docker_build.ps1 logs' 查看日志"
    }
    else {
        Write-Error-Msg "服务启动失败"
        exit 1
    }
}

# 停止服务
function Stop-Services {
    Write-Info "停止服务..."
    docker-compose down
    if ($LASTEXITCODE -eq 0) {
        Write-Success "服务已停止"
    }
}

# 重启服务
function Restart-Services {
    Write-Info "重启服务..."
    docker-compose restart
    if ($LASTEXITCODE -eq 0) {
        Write-Success "服务已重启"
    }
}

# 查看日志
function Show-Logs {
    param([string]$Option)
    
    Write-Info "查看日志..."
    if ($Option -eq "-f" -or $Option -eq "--follow") {
        docker-compose logs -f
    }
    else {
        docker-compose logs
    }
}

# 查看状态
function Show-Status {
    Write-Info "服务运行状态:"
    docker-compose ps
}

# 清理环境
function Clean-Environment {
    Write-Warning "这将删除所有容器、镜像和数据卷"
    $confirmation = Read-Host "确定要继续吗? (y/N)"
    
    if ($confirmation -eq "y" -or $confirmation -eq "Y") {
        Write-Info "清理容器和网络..."
        docker-compose down -v
        
        Write-Info "删除镜像..."
        docker-compose down --rmi all
        
        Write-Success "清理完成"
    }
    else {
        Write-Info "已取消清理操作"
    }
}

# 启动开发环境
function Start-DevEnvironment {
    Write-Info "启动开发环境..."
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
    if ($LASTEXITCODE -eq 0) {
        Write-Success "开发环境已启动"
        Write-Info "代码更改将自动重载"
    }
}

# 启动生产环境
function Start-ProdEnvironment {
    Write-Info "启动生产环境..."
    docker-compose up -d --build
    if ($LASTEXITCODE -eq 0) {
        Write-Success "生产环境已启动"
    }
}

# 主函数
function Main {
    # 检查 Docker 环境
    if (-not (Test-Docker)) {
        exit 1
    }
    
    # 解析命令
    switch ($Command.ToLower()) {
        "build" {
            Build-Image
        }
        "up" {
            Start-Services
        }
        "start" {
            Start-Services
        }
        "down" {
            Stop-Services
        }
        "stop" {
            Stop-Services
        }
        "restart" {
            Restart-Services
        }
        "logs" {
            Show-Logs -Option $Option
        }
        "ps" {
            Show-Status
        }
        "status" {
            Show-Status
        }
        "clean" {
            Clean-Environment
        }
        "dev" {
            Initialize-Environment
            Start-DevEnvironment
        }
        "prod" {
            Initialize-Environment
            Start-ProdEnvironment
        }
        "init" {
            Initialize-Environment
        }
        "help" {
            Show-Help
        }
        "--help" {
            Show-Help
        }
        "-h" {
            Show-Help
        }
        default {
            Write-Error-Msg "未知命令: $Command"
            Write-Host ""
            Show-Help
            exit 1
        }
    }
}

# 执行主函数
Main

