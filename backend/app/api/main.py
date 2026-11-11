"""FastAPI主应用"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings, validate_config, print_config
from ..infra.logging import configure_logging
from ..services.trip_service import TripService, get_trip_service
from .middleware import request_id_middleware
from .routes import trip, poi, map as map_routes
from .v1.router import router as v1_router

# 获取配置
settings = get_settings()
configure_logging(settings.log_level)

# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于确定性 DAG 的镇江旅行规划助手 API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.middleware("http")(request_id_middleware)

# 注册路由
app.include_router(v1_router, prefix="/api")
app.include_router(trip.router, prefix="/api")
app.include_router(poi.router, prefix="/api")
app.include_router(map_routes.router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("\n" + "="*60)
    print(f"🚀 {settings.app_name} v{settings.app_version}")
    print("="*60)
    
    # 打印配置信息
    print_config()
    
    # 验证配置
    try:
        validate_config()
        print("\n✅ 配置验证通过")
    except ValueError as e:
        print(f"\n❌ 配置验证失败:\n{e}")
        print("\n请检查.env文件并确保所有必要的配置项都已设置")
        raise
    
    print("\n" + "="*60)
    print("📚 API文档: http://localhost:8000/docs")
    print("📖 ReDoc文档: http://localhost:8000/redoc")
    print("="*60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print("\n" + "="*60)
    print("👋 应用正在关闭...")
    print("="*60 + "\n")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health(service: TripService = Depends(get_trip_service)):
    """健康检查：不调用 LLM，不泄露密钥。"""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        **service.health(),
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )

