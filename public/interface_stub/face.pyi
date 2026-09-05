# @version 1.0.2
"""FaceMatch 人脸档案匹配接口契约存根（spec add-vlm-frame-filter-face-match Task 1 冻结）。

@1.0.1 PATCH: match 返回语义修正——对齐 spec 决策点 #9 与实现。
@1.0.2 PATCH: match 方法体 Returns 同步修正（1.0.1 仅改头部注记、方法体漏改，GN-004 交付审查 F-A 人类授权后闭合）。

源真理: 后端人脸档案匹配功能（face_match 配置段，见 server/config.py FaceMatchConfig）
当前状态: 契约冻结——4 异步方法 + 1 同步状态方法 + 工厂函数；实现在后续 Task 落地
配置: public/config_template/radix_config.json face_match 段（CXO_FACE_* 环境变量可覆盖）
"""

from typing import Any, Dict, List


class FaceServiceUnavailable(RuntimeError):
    """人脸服务不可用异常。

    raised 当 face_match.enabled=false（功能未启用）或底层模型/端点初始化失败时，
    由 register/match/list_profiles/delete_profile 抛出；调用方（如帧过滤器、
    工具注册层）必须捕获该异常并按 filter_fail_mode / 工具错误语义降级处理。
    """


class FaceProfileService:
    """人脸档案服务：注册、匹配、列举、删除人脸档案，以及运行状态查询。

    档案持久化结构见 public/schema/face_profile.schema.json，存储路径由
    radix_config.face_match.store_path 指定；相似度阈值与单帧人脸上限由
    sim_threshold / max_faces_per_frame 配置。
    """

    async def register(self, name: str, image_b64: str) -> Dict[str, Any]:
        """注册（或覆盖）指定姓名的人脸档案。

        Args:
            name: 人脸档案唯一标识名，非空；同名已存在时覆盖其特征向量与创建时间。
            image_b64: JPEG/PNG 图像的 base64 编码字符串，须包含至少一张可检出人脸。

        Returns:
            Dict[str, Any]: 写入结果，至少含 ``name``（档案名）、``faces_detected``
            （检出人脸数）、``created_at``（ISO 8601 创建时间）。

        Raises:
            ValueError: name 为空 / 图像解码失败 / 未检出人脸。
            FaceServiceUnavailable: 服务未启用或底层模型初始化失败。
        """
        ...

    async def match(self, image_b64: str) -> List[Dict[str, Any]]:
        """对输入图像做人脸检测与档案匹配。

        Args:
            image_b64: JPEG/PNG 图像的 base64 编码字符串；最多处理
                radix_config.face_match.max_faces_per_frame 张人脸。

        Returns:
            List[Dict[str, Any]]: 与检出人脸一一对应的列表（每张脸一项），
            命中项含 ``name``（档案名）、``similarity``（相似度 0-1，
            ≥ sim_threshold）、``bbox``；未命中项含 ``unknown=True``、
            ``best_similarity``（全档案最高相似度）、``bbox``；无人脸返回
            空列表（不视为错误）。

        Raises:
            ValueError: 图像解码失败。
            FaceServiceUnavailable: 服务未启用或底层模型/端点不可用。
        """
        ...

    async def list_profiles(self) -> List[Dict[str, Any]]:
        """列出现有全部人脸档案。

        Returns:
            List[Dict[str, Any]]: 档案列表，每项含 ``name`` 与 ``created_at``
            （不含特征向量本体，避免大对象透出）；无档案返回空列表。

        Raises:
            FaceServiceUnavailable: 服务未启用。
        """
        ...

    async def delete_profile(self, name: str) -> bool:
        """按姓名删除指定人脸档案。

        Args:
            name: 待删除的档案名。

        Returns:
            bool: 删除成功返回 True；档案不存在返回 False（幂等，不抛错）。

        Raises:
            FaceServiceUnavailable: 服务未启用或档案存储不可写。
        """
        ...

    def get_status(self) -> Dict[str, Any]:
        """查询人脸服务运行状态（同步方法，不触发模型加载）。

        Returns:
            Dict[str, Any]: 状态字典，至少含 ``enabled``（是否启用）、
            ``provider``（local|external）、``ready``（模型/端点是否就绪）、
            ``profile_count``（当前档案数）。
        """
        ...


def get_face_profile_service() -> FaceProfileService:
    """获取 FaceProfileService 单例（工厂入口，对齐其他服务的模块级工厂模式）。

    首次调用按 radix_config.face_match 配置惰性实例化；enabled=false 时
    仍返回实例，但各方法将抛出 FaceServiceUnavailable。

    Returns:
        FaceProfileService: 进程级单例。

    Raises:
        FaceServiceUnavailable: 配置节缺失或初始化参数非法且无法回退时。
    """
    ...
