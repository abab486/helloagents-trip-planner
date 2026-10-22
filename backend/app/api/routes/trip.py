"""旅行规划API路由"""

import asyncio

from fastapi import APIRouter, HTTPException
from ...models.schemas import (
    TripRequest,
    TripPlanResponse,
    ErrorResponse
)
from ...agents.trip_planner_agent import get_trip_planner_agent

router = APIRouter(prefix="/trip", tags=["旅行规划"])


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求,生成详细的旅行计划"
)
async def plan_trip(request: TripRequest):
    """
    生成旅行计划

    Args:
        request: 旅行请求参数

    Returns:
        旅行计划响应
    """
    try:
        print(f"\n{'='*60}")
        print(f"📥 收到旅行规划请求:")
        print(f"   城市: {request.city}")
        print(f"   日期: {request.start_date} - {request.end_date}")
        print(f"   天数: {request.travel_days}")
        print(f"{'='*60}\n")

        # 获取Agent实例（首次初始化会启动 MCP，放到线程池避免阻塞事件循环）
        print("🔄 获取多智能体系统实例...")
        agent = await asyncio.to_thread(get_trip_planner_agent)

        # 生成旅行计划（三路 Agent 并行，不能阻塞事件循环）
        print("🚀 开始生成旅行计划...")
        trip_plan = await agent.plan_trip(request)

        print("✅ 旅行计划生成成功,准备返回响应\n")

        message = "旅行计划生成成功"
        if trip_plan.budget_limit and trip_plan.over_budget:
            message = f"旅行计划生成成功，超出预算 {trip_plan.over_budget} 元"

        return TripPlanResponse(
            success=True,
            message=message,
            data=trip_plan
        )

    except Exception as e:
        print(f"❌ 生成旅行计划失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"生成旅行计划失败: {str(e)}"
        )


@router.get(
    "/health",
    summary="健康检查",
    description="检查旅行规划服务是否正常"
)
async def health_check():
    """健康检查"""
    try:
        # 检查Agent是否可用
        agent = get_trip_planner_agent()
        
        return {
            "status": "healthy",
            "service": "trip-planner",
            "agent_name": agent.agent.name,
            "tools_count": len(agent.agent.list_tools())
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}"
        )

