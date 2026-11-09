"""列表接口的统一分页辅助。

约定：**响应体保持为数组**（向后兼容），总数通过响应头返回：

- ``X-Total-Count``：满足筛选条件的总条数
- ``X-Skip`` / ``X-Limit``：本次请求的偏移与上限，便于前端计算页码

之所以不改成 ``{items, total}`` 包装，是为了不触动现有列表端点的响应结构——
否则所有前端调用点、OpenAPI 描述与测试都要同时改写，收益相同而风险高得多。
需要完整 ``{"total": ..., "items": ...}`` 结构的场景（如导入暂存列表）保持各自实现。
"""
from fastapi import Response


def paginate(query, skip, limit, response: Response, transform=None):
    """对 SQLAlchemy 查询分页，并把总数写进响应头。

    Args:
        query: 已应用筛选/排序的查询对象
        skip: 偏移量
        limit: 每页条数
        response: 注入的 Response，用于附加计数头
        transform: 可选，把 ORM 对象映射为 dict 的函数
    """
    total = query.count()
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Skip"] = str(skip)
    response.headers["X-Limit"] = str(limit)

    items = query.offset(skip).limit(limit).all()
    if transform is None:
        return items
    return [transform(item) for item in items]
