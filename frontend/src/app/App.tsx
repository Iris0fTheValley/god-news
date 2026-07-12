import {DatabaseZap, Radio, Rows3} from 'lucide-react';
import {Link, Navigate, Route, Routes, useLocation} from 'react-router-dom';

import {StoryListPage} from '../features/stories/StoryListPage';
import {StoryWorkbenchPage} from '../features/stories/StoryWorkbenchPage';
import {SourceManagementPage} from '../features/sources/SourceManagementPage';

function Shell() {
  const location = useLocation();
  const inStories = location.pathname.startsWith('/stories');
  const inSources = location.pathname.startsWith('/sources');
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <header className="masthead">
        <Link className="brand" to="/stories" aria-label="god-news 故事看板">
          <span className="brand-mark" aria-hidden="true">
            <Radio size={20} strokeWidth={2.2} />
          </span>
          <span>
            <strong>god-news</strong>
            <small>好事播报制作台</small>
          </span>
        </Link>
        <nav aria-label="主导航">
          <Link className={inStories ? 'nav-link active' : 'nav-link'} to="/stories">
            <Rows3 size={18} aria-hidden="true" />
            故事队列
          </Link>
          <Link className={inSources ? 'nav-link active' : 'nav-link'} to="/sources">
            <DatabaseZap size={18} aria-hidden="true" />
            来源运行
          </Link>
        </nav>
        <div className="system-pulse" role="status">
          <span aria-hidden="true" /> 本地制作模式
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/stories" element={<StoryListPage />} />
          <Route path="/stories/:storyId" element={<StoryWorkbenchPage />} />
          <Route path="/sources" element={<SourceManagementPage />} />
          <Route path="*" element={<Navigate replace to="/stories" />} />
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  return <Shell />;
}
