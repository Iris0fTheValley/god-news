import {useQuery} from '@tanstack/react-query';
import {Keyboard, Menu, Radio, X} from 'lucide-react';
import {useEffect, useState} from 'react';
import {Link, Navigate, Route, Routes, useLocation, useNavigate} from 'react-router-dom';

import {getReadiness} from '../api/client';
import {KeyboardShortcuts} from '../components/KeyboardShortcuts';
import {ToastProvider} from '../components/Toast';
import {BgmPage} from '../features/bgm/BgmPage';
import {VisualAssetsPage} from '../features/library/VisualAssetsPage';
import {OpsPage} from '../features/ops/OpsPage';
import {RolesPage} from '../features/roles/RolesPage';
import {SourceManagementPage} from '../features/sources/SourceManagementPage';
import {SourceRunsPage} from '../features/sources/SourceRunsPage';
import {StoryListPage} from '../features/stories/StoryListPage';
import {StoryWorkbenchPage} from '../features/stories/StoryWorkbenchPage';
import {TemplateLabPage} from '../features/template-lab/TemplateLabPage';
import {VideoBatchesPage} from '../features/video/VideoBatchesPage';
import {VisualModulesPage} from '../features/visual-modules/VisualModulesPage';
import {queryKeys} from '../api/queryKeys';
import {
  NAVIGATION_GROUPS,
  NAVIGATION_ITEMS,
  navigationItemForPath,
} from './navigation';

function NavigationLink({
  item,
  pathname,
  onNavigate,
}: {
  item: (typeof NAVIGATION_ITEMS)[number];
  pathname: string;
  onNavigate: () => void;
}) {
  const active = pathname === item.to || pathname.startsWith(`${item.to}/`);
  return (
    <Link
      className={active ? 'side-nav-link active' : 'side-nav-link'}
      to={item.to}
      aria-current={active ? 'page' : undefined}
      onClick={onNavigate}
    >
      <item.icon size={18} aria-hidden="true" />
      <span>
        <strong>{item.label}</strong>
        <small>{item.description}</small>
      </span>
      {item.shortcut !== undefined ? <kbd>{item.shortcut}</kbd> : null}
    </Link>
  );
}

function LegacyRedirect({to}: {to: string}) {
  const location = useLocation();
  return (
    <Navigate
      replace
      to={{
        pathname: to,
        search: location.search,
        hash: location.hash,
      }}
    />
  );
}

function Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const currentItem = navigationItemForPath(location.pathname);
  const readiness = useQuery({
    queryKey: queryKeys.readiness,
    queryFn: getReadiness,
    refetchInterval: 30_000,
    retry: 1,
  });

  useEffect(() => {
    window.scrollTo({top: 0, left: 0});
  }, [location.pathname]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target;
      const editing = target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || (target instanceof HTMLElement && target.isContentEditable);
      if (event.key === 'Escape') {
        if (shortcutsOpen) setShortcutsOpen(false);
        if (mobileNavOpen) setMobileNavOpen(false);
        return;
      }
      if (editing) return;
      if (event.key === '?' && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        setShortcutsOpen((previous) => !previous);
        return;
      }
      if (event.key === '/') {
        const search = document.querySelector<HTMLInputElement>('[data-global-search]');
        if (search !== null) {
          event.preventDefault();
          search.focus();
        }
        return;
      }
      if (event.key.toLowerCase() === 'n') {
        const createButton = document.querySelector<HTMLButtonElement>('[data-new-story]');
        if (createButton !== null) {
          event.preventDefault();
          createButton.click();
        }
        return;
      }
      const destination = NAVIGATION_ITEMS.find((item) => item.shortcut === event.key);
      if (destination !== undefined && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setMobileNavOpen(false);
        void navigate(destination.to);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mobileNavOpen, navigate, shortcutsOpen]);

  const systemState = readiness.isLoading
    ? {tone: 'loading', label: '检查制作系统'}
    : readiness.data?.ready === true
      ? {tone: 'ready', label: '制作系统就绪'}
      : {tone: 'blocked', label: '系统需要处理'};

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className={mobileNavOpen ? 'side-rail open' : 'side-rail'} aria-label="主导航">
        <div className="side-rail-brand">
          <Link className="brand" to="/stories" aria-label="god-news 故事制作台">
            <span className="brand-mark" aria-hidden="true">
              <Radio size={20} strokeWidth={2.2} />
            </span>
            <span>
              <strong>god-news</strong>
              <small>好消息节目制作台</small>
            </span>
          </Link>
          <button
            className="icon-button side-rail-close"
            type="button"
            aria-label="关闭导航"
            onClick={() => setMobileNavOpen(false)}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <nav className="side-navigation">
          {NAVIGATION_GROUPS.map((group) => (
            <section className="side-nav-group" key={group.label}>
              <h2>{group.label}</h2>
              {group.items.map((item) => (
                <NavigationLink
                  key={item.to}
                  item={item}
                  pathname={location.pathname}
                  onNavigate={() => setMobileNavOpen(false)}
                />
              ))}
            </section>
          ))}
        </nav>
        <div className="side-rail-footer">
          <Link
            className={`system-readiness ${systemState.tone}`}
            to="/collection/sources"
            aria-label={`${systemState.label}，查看来源和系统状态`}
          >
            <span aria-hidden="true" />
            <strong>{systemState.label}</strong>
            <small>
              {readiness.data?.checks.length ?? 0} 项检查
            </small>
          </Link>
          <button
            className="shortcut-trigger"
            type="button"
            onClick={() => setShortcutsOpen(true)}
          >
            <Keyboard size={15} aria-hidden="true" />
            快捷键
            <kbd>?</kbd>
          </button>
        </div>
      </aside>
      {mobileNavOpen ? (
        <button
          className="nav-backdrop"
          type="button"
          aria-label="关闭导航"
          onClick={() => setMobileNavOpen(false)}
        />
      ) : null}
      <div className="app-workspace">
        <header className="workspace-bar">
          <button
            className="icon-button mobile-nav-trigger"
            type="button"
            aria-label="打开导航"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen(true)}
          >
            <Menu size={19} aria-hidden="true" />
          </button>
          <div>
            <span>{NAVIGATION_GROUPS.find((group) => group.items.includes(currentItem))?.label}</span>
            <strong>{currentItem.label}</strong>
          </div>
          <div className={`workspace-health ${systemState.tone}`} role="status">
            <span aria-hidden="true" />
            {systemState.label}
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <Routes>
            <Route path="/stories" element={<StoryListPage />} />
            <Route path="/stories/:storyId" element={<StoryWorkbenchPage />} />
            <Route path="/collection/sources" element={<SourceManagementPage />} />
            <Route path="/collection/runs" element={<SourceRunsPage />} />
            <Route path="/production/batches" element={<VideoBatchesPage />} />
            <Route path="/library/visual-assets" element={<VisualAssetsPage />} />
            <Route path="/library/roles" element={<RolesPage />} />
            <Route path="/library/audio" element={<BgmPage />} />
            <Route path="/visual/modules" element={<VisualModulesPage />} />
            <Route path="/visual/scene-lab" element={<TemplateLabPage />} />
            <Route path="/system/operations" element={<OpsPage />} />

            <Route path="/sources" element={<LegacyRedirect to="/collection/sources" />} />
            <Route path="/source-runs" element={<LegacyRedirect to="/collection/runs" />} />
            <Route path="/video" element={<LegacyRedirect to="/production/batches" />} />
            <Route path="/roles" element={<LegacyRedirect to="/library/roles" />} />
            <Route path="/bgm" element={<LegacyRedirect to="/library/audio" />} />
            <Route path="/template-lab" element={<LegacyRedirect to="/visual/scene-lab" />} />
            <Route path="/ops" element={<LegacyRedirect to="/system/operations" />} />
            <Route path="*" element={<Navigate replace to="/stories" />} />
          </Routes>
        </main>
      </div>
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
