import asyncio
import os
import shutil
import tempfile

import pytest

from backend.core.memory.chroma_store import ChromaVectorStore

pytest.importorskip("chromadb", reason="chromadb not installed")


class TestChromaVectorStore:
    """Chroma向量存储测试"""

    @pytest.fixture
    def chroma_store(self):
        """创建Chroma向量存储实例（内存模式）"""
        store = ChromaVectorStore(
            db_path=":memory:", collection_name="test_collection", vector_size=128, persistent=False
        )
        yield store
        store.close()

    def test_initialization(self, chroma_store):
        """测试初始化"""
        assert chroma_store.is_available()

    def test_get_collection_info(self, chroma_store):
        """测试获取集合信息"""
        info = chroma_store.get_collection_info()
        assert info["status"] == "available"
        assert info["name"] == "test_collection"
        assert info["count"] == 0

    @pytest.mark.asyncio
    async def test_add_vector(self, chroma_store):
        """测试添加向量"""
        embedding = [0.1] * 128
        success = await chroma_store.add_memory_vector(
            memory_id=1, content="测试内容", embedding=embedding, metadata={"type": "test"}
        )
        assert success is True

        info = chroma_store.get_collection_info()
        assert info["count"] == 1

    @pytest.mark.asyncio
    async def test_search_similar(self, chroma_store):
        """测试相似搜索"""
        embedding1 = [0.1] * 128
        embedding2 = [0.9] * 128

        await chroma_store.add_memory_vector(
            memory_id=1, content="相似内容", embedding=embedding1, metadata={"type": "test"}
        )

        await chroma_store.add_memory_vector(
            memory_id=2, content="不同内容", embedding=embedding2, metadata={"type": "test"}
        )

        results = await chroma_store.search_similar(query_embedding=embedding1, limit=10)

        assert len(results) >= 1
        assert results[0]["id"] in [1, 2]
        assert results[0]["score"] > 0.5

    @pytest.mark.asyncio
    async def test_delete_vector(self, chroma_store):
        """测试删除向量"""
        embedding = [0.1] * 128

        await chroma_store.add_memory_vector(memory_id=1, content="测试内容", embedding=embedding)

        assert await chroma_store.check_exists(1) is True

        success = await chroma_store.delete_by_memory_id(1)
        assert success is True

        assert await chroma_store.check_exists(1) is False

    @pytest.mark.asyncio
    async def test_get_vector_by_id(self, chroma_store):
        """测试通过ID获取向量"""
        embedding = [0.1] * 128

        await chroma_store.add_memory_vector(
            memory_id=1, content="测试内容", embedding=embedding, metadata={"importance": 5}
        )

        result = await chroma_store.get_vector_by_id(1)
        assert result is not None
        assert result["content"] == "测试内容"
        assert result["metadata"]["importance"] == 5

    def test_clear_collection(self, chroma_store):
        """测试清空集合"""
        embedding = [0.15] * 128
        asyncio.run(
            chroma_store.add_memory_vector(memory_id=999, content="测试清空", embedding=embedding)
        )

        info = chroma_store.get_collection_info()
        assert info["count"] >= 1

        success = chroma_store.clear_collection()
        assert success is True

        info = chroma_store.get_collection_info()
        assert info["count"] == 0


class TestChromaVectorStorePersistent:
    """Chroma向量存储持久化测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_persistence(self, temp_dir):
        """测试数据持久化"""
        db_path = os.path.join(temp_dir, "chroma_persist")
        embedding = [0.1] * 128

        store1 = ChromaVectorStore(
            db_path=db_path, collection_name="persist_test", vector_size=128, persistent=True
        )

        await store1.add_memory_vector(memory_id=1, content="持久化测试", embedding=embedding)

        info1 = store1.get_collection_info()
        assert info1["count"] == 1

        store1.close()

        store2 = ChromaVectorStore(
            db_path=db_path, collection_name="persist_test", vector_size=128, persistent=True
        )

        info2 = store2.get_collection_info()
        assert info2["count"] == 1

        exists = await store2.check_exists(1)
        assert exists is True

        store2.close()
