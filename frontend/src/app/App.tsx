import {Clapperboard, DatabaseZap, FolderOpen, Keyboard, Music, Radio, Rows3, UserCog, Wrench} from 'lucide-react';
import {useEffect, useState} from 'react';
import {Link, Navigate, Route, Routes, useLocation} from 'react-router-dom';

import {KeyboardShortcuts} from '../components/KeyboardShortcuts';
import {ToastProvider} from '../components/Toast';
import {BgmPage} from '../features/bgm/BgmPage';
import {OpsPage} from '../features/ops/OpsPage';
import {RolesPage} from '../features/roles/RolesPage';
import {SourceManagementPage} from '../features/sources/SourceManagementPage';
import {SourceRunsPage} from '../features/sources/SourceRunsPage';
import {StoryListPage} from '../features/stories/StoryListPage';
import {StoryWorkbenchPage} from '../features/stories/StoryWorkbenchPage';
import {VideoBatchesPage} from '../features/video/VideoBatchesPage';

const NAV_ITEMS = [
  {to: '/stories', label: '故事队列', icon: Rows3},
  {to: '/sources', label: '来源运行', icon: DatabaseZap},
  {to: '/roles', label: '角色', icon: UserCog},
  {to: '/video', label: '视频批次', icon: Clapperboard},
  {to: '/source-runs', label: '采集记录', icon: FolderOpen},
  {to: '/bgm', label: 'BGM', icon: Music},
  {to: '/ops', label: '运维日志', icon: Wrench},
];

function Shell() {
  const location = useLocation();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return;
      if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setShortcutsOpen((prev) => !prev);
      }
      if (e.key === 'Escape' && shortcutsOpen) {
        setShortcutsOpen(false);
        return;
      }
      // Number nav
      if (e.key >= '1' && e.key <= String(NAV_ITEMS.length) && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const idx = Number(e.key) - 1;
        window.location.hash = NAV_ITEMS[idx].to;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [shortcutsOpen]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
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
          {NAV_ITEMS.slice(0, 4).map((item) => (
            <Link
              key={item.to}
              className={location.pathname.startsWith(item.to) ? 'nav-link active' : 'nav-link'}
              to={item.to}
            >
              <item.icon size={18} aria-hidden="true" />
              {item.label}
            </Link>
          ))}
          {/* Overflow — hide on desktop if more than 4 visible; always show on mobile */}
          <div className="nav-overflow">
            {NAV_ITEMS.slice(4).map((item) => (
              <Link
                key={item.to}
                className={location.pathname.startsWith(item.to) ? 'nav-link active' : 'nav-link'}
                to={item.to}
                style={{fontSize: '13px'}}
              >
                <item.icon size={16} aria-hidden="true" />
                {item.label}
              </Link>
            ))}
          </div>
        </nav>
        <div className="system-pulse" role="status">
          <span aria-hidden="true" />
          本地制作模式
          <button
            className="icon-button"
            type="button"
            aria-label="查看快捷键 (? 键)"
            onClick={() => setShortcutsOpen(true)}
            style={{marginLeft: 8, width: 28, height: 28}}
          >
            <Keyboard size={14} aria-hidden="true" />
          </button>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/stories" element={<StoryListPage />} />
          <Route path="/stories/:storyId" element={<StoryWorkbenchPage />} />
          <Route path="/sources" element={<SourceManagementPage />} />
          <Route path="/roles" element={<RolesPage />} />
          <Route path="/video" element={<VideoBatchesPage />} />
          <Route path="/source-runs" element={<SourceRunsPage />} />
          <Route path="/bgm" element={<BgmPage />} />
          <Route path="/ops" element={<OpsPage />} />
          <Route path="*" element={<Navigate replace to="/stories" />} />
        </Routes>
      </main>
      <KeyboardShortcuts open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}

export function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}
