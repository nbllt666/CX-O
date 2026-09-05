import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import CorpusPage from "./pages/CorpusPage";
import DatasetsPage from "./pages/DatasetsPage";
import ModelsPage from "./pages/ModelsPage";
import TrainPage from "./pages/TrainPage";
import WorkflowPage from "./pages/WorkflowPage";

const NAV_ITEMS = [
  { to: "/datasets", label: "数据集管理", desc: "speaker 目录与音频导入" },
  { to: "/corpus", label: "批量语料生成", desc: "VoxCPM 文本转训练语料" },
  { to: "/train", label: "训练控制台", desc: "预处理 / 训练 / 进度" },
  { to: "/models", label: "模型库", desc: "模型列表与试听推理" },
  { to: "/workflow", label: "工作流总览", desc: "三步训练编排" },
];

/** 模型工作站独立前端：侧边导航布局 + 五页面路由 */
export default function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <h1>模型工作站</h1>
            <p>CXO-ModelStation</p>
          </div>
          <nav className="sidebar-nav" aria-label="主导航">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
              >
                <span className="nav-label">{item.label}</span>
                <span className="nav-desc">{item.desc}</span>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-footer">So-VITS-SVC 训练全链路 · 后端端口 8300</div>
        </aside>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Navigate to="/datasets" replace />} />
            <Route path="/datasets" element={<DatasetsPage />} />
            <Route path="/corpus" element={<CorpusPage />} />
            <Route path="/train" element={<TrainPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/workflow" element={<WorkflowPage />} />
            <Route path="*" element={<Navigate to="/datasets" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
