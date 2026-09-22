"""Repository 基础类"""

from typing import TypeVar, Generic, Type, Optional, Sequence, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """通用 Repository 基类，提供基础 CRUD 操作"""

    def __init__(self, db: AsyncSession, model: Type[T]):
        self.db = db
        self.model = model

    def _select(self):
        return select(self.model)

    async def get_by_id(self, id_value: Any, id_field: str = "id") -> Optional[T]:
        """根据 ID 获取单条记录"""
        stmt = self._select().where(getattr(self.model, id_field) == id_value)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[Any] = None,
    ) -> Sequence[T]:
        """获取所有记录（支持分页）"""
        stmt = self._select()
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """获取记录总数"""
        stmt = select(func.count()).select_from(self._select().subquery())
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def create(self, entity: T) -> T:
        """创建记录"""
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def update(self, entity: T) -> T:
        """更新记录"""
        await self.db.flush()
        return entity

    async def delete(self, entity: T) -> None:
        """删除记录"""
        await self.db.delete(entity)
        await self.db.flush()

    async def commit(self) -> None:
        """提交事务"""
        await self.db.commit()

    async def refresh(
        self, entity: T, attribute_names: Optional[list[str]] = None
    ) -> T:
        """刷新实体"""
        await self.db.refresh(entity, attribute_names=attribute_names)
        return entity
