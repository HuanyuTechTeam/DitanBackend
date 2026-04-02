#!/bin/bash

# Docker 构建和运行脚本
# 用于快速构建和启动 DitanBackend 服务

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示使用说明
show_help() {
    cat << EOF
DitanBackend Docker 管理脚本

使用方式:
    $0 [命令] [选项]

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
    -d, --detach    后台运行（默认）
    -f, --follow    跟踪日志输出
    --build         强制重新构建镜像

示例:
    $0 build                # 构建镜像
    $0 up                   # 启动服务
    $0 logs -f              # 实时查看日志
    $0 down                 # 停止服务
    $0 dev                  # 启动开发环境
    $0 clean                # 清理环境

EOF
}

# 检查 Docker 是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    print_success "Docker 环境检查通过"
}

# 初始化环境
init_env() {
    print_info "初始化环境..."
    
    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            cp .env.example .env
            print_success "已创建 .env 文件，请根据实际情况修改配置"
            print_warning "请修改 .env 文件中的 DATABASE_PASSWORD"
        else
            print_error ".env.example 文件不存在"
            exit 1
        fi
    else
        print_info ".env 文件已存在，跳过创建"
    fi
    
    # 创建日志目录
    mkdir -p logs
    print_success "日志目录已创建"
}

# 构建镜像
build_image() {
    print_info "开始构建本地开发镜像..."
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml build app "$@"
    print_success "本地开发镜像构建完成"
}

# 启动服务
start_services() {
    local detach="-d"
    local build_flag=""
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -d|--detach)
                detach="-d"
                shift
                ;;
            --build)
                build_flag="--build"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    print_info "启动服务..."
    docker-compose up $detach $build_flag
    
    if [ "$detach" = "-d" ]; then
        print_success "服务已在后台启动"
        print_info "访问 http://localhost:8000 查看服务"
        print_info "访问 http://localhost:8000/docs 查看 API 文档"
        print_info "使用 '$0 logs' 查看日志"
    fi
}

# 停止服务
stop_services() {
    print_info "停止服务..."
    docker-compose down
    print_success "服务已停止"
}

# 重启服务
restart_services() {
    print_info "重启服务..."
    docker-compose restart
    print_success "服务已重启"
}

# 查看日志
view_logs() {
    local follow_flag=""
    
    # 检查是否有 -f 参数
    for arg in "$@"; do
        if [ "$arg" = "-f" ] || [ "$arg" = "--follow" ]; then
            follow_flag="-f"
            break
        fi
    done
    
    print_info "查看日志..."
    docker-compose logs $follow_flag
}

# 查看状态
view_status() {
    print_info "服务运行状态:"
    docker-compose ps
}

# 清理环境
clean_env() {
    print_warning "这将删除所有容器、镜像和数据卷"
    read -p "确定要继续吗? (y/N) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "清理容器和网络..."
        docker-compose down -v
        
        print_info "删除镜像..."
        docker-compose down --rmi all
        
        print_success "清理完成"
    else
        print_info "已取消清理操作"
    fi
}

# 启动开发环境
start_dev() {
    print_info "启动开发环境..."
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
    print_success "开发环境已启动"
    print_info "代码更改将自动重载"
}

# 启动生产环境
start_prod() {
    print_info "启动生产环境..."
    docker-compose up -d --build
    print_success "生产环境已启动"
}

# 主函数
main() {
    # 检查 Docker 环境
    check_docker
    
    # 解析命令
    case "${1:-help}" in
        build)
            shift
            build_image "$@"
            ;;
        up|start)
            shift
            start_services "$@"
            ;;
        down|stop)
            stop_services
            ;;
        restart)
            restart_services
            ;;
        logs)
            shift
            view_logs "$@"
            ;;
        ps|status)
            view_status
            ;;
        clean)
            clean_env
            ;;
        dev)
            init_env
            start_dev
            ;;
        prod)
            init_env
            start_prod
            ;;
        init)
            init_env
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $1"
            echo
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"

