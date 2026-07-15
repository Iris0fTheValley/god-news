import {useMutation, useQuery} from '@tanstack/react-query';
import {Activity, CircleAlert, RefreshCw, ShieldCheck} from 'lucide-react';
import {useState} from 'react';

import {diagnoseSource, getSourceHealth} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {SourceHealth} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';

const SOURCE_LABELS: Record<SourceHealth['source'], string> = {
  dazhong: '大众新闻 · 开屏见好',
  reddit: 'Reddit · HumansBeingBros',
  guardian: 'The Guardian · Kindness',
  pikabu: 'Pikabu · Доброта',
};

const ACCESS_LABELS: Record<SourceHealth['access_method'], string> = {
  official_api: '官方 API',
  authorized_public_page: '授权公开页面',
  typed_contract_only: '仅类型契约',
};

function availability(item: SourceHealth) {
  if (!item.enabled) return {tone: 'muted', label: '已停用'};
  if (!item.configured) return {tone: 'warning', label: '缺少配置'};
  if (!item.contract_ok) return {tone: 'danger', label: '契约异常'};
  if (!item.authorized) return {tone: 'warning', label: '等待授权'};
  if (item.reachable === false) return {tone: 'danger', label: '网络不可达'};
  if (item.reachable === true) return {tone: 'ready', label: '可运行'};
  return {tone: 'neutral', label: '已配置 · 未探测'};
}

function Fact({ok, children}: {ok: boolean; children: string}) {
  return (
    <li className={ok ? 'source-fact ok' : 'source-fact'}>
      {ok ? <ShieldCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}
      {children}
    </li>
  );
}

export function SourceManagementPage() {
  const [probeNetwork, setProbeNetwork] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.sourceHealth(probeNetwork),
    queryFn: () => getSourceHealth(probeNetwork),
  });
  const diagnostic = useMutation({mutationFn: (source: SourceHealth['source']) => diagnoseSource(source)});

  return (
    <div className="page sources-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">INGEST CONTROL</p>
          <h1>来源运行</h1>
          <p>授权、契约与网络状态分别核验。只有全部满足的来源才会进入自动采集。</p>
        </div>
        <button
          className="button primary"
          type="button"
          disabled={query.isFetching}
          onClick={() => {
            if (!probeNetwork) setProbeNetwork(true);
            else void query.refetch();
          }}
        >
          <RefreshCw className={query.isFetching ? 'spin' : ''} size={17} aria-hidden="true" />
          {query.isFetching ? '正在核验' : '核验网络'}
        </button>
      </div>

      <div className="source-policy-note">
        <Activity size={19} aria-hidden="true" />
        <div>
          <strong>可达不等于已授权</strong>
          <p>公开页面来源需要显式使用确认；Reddit 与 Guardian 只接受官方凭据。验证码会立即停止该来源。</p>
        </div>
      </div>

      {query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data === undefined ? (
        <div className="loading-state">正在读取四个固定来源的运行契约…</div>
      ) : (
        <>
          <div className="source-summary metadata">
            <span>{query.data.sources.filter((item) => item.authorized).length}/4 已授权</span>
            <span>{query.data.sources.filter((item) => item.contract_ok).length}/4 契约正常</span>
            <span>{query.data.network_probed ? '本次包含网络探测' : '本次未进行网络探测'}</span>
            <time dateTime={query.data.checked_at}>
              {query.data.checked_at === undefined
                ? '检查时间未知'
                : new Date(query.data.checked_at).toLocaleString()}
            </time>
          </div>
          <div className="source-grid">
            {query.data.sources.map((item) => {
              const state = availability(item);
              return (
                <article className="source-card" key={item.source}>
                  <header>
                    <div>
                      <p className="metadata">{item.source}</p>
                      <h2>{SOURCE_LABELS[item.source]}</h2>
                    </div>
                    <span className={`source-state ${state.tone}`}>{state.label}</span>
                  </header>
                  <p className="source-access">{ACCESS_LABELS[item.access_method]}</p>
                  <ul className="source-facts">
                    <Fact ok={item.enabled}>采集器已启用</Fact>
                    <Fact ok={item.configured}>凭据或端点配置完整</Fact>
                    <Fact ok={item.authorized}>访问方式已获操作方确认</Fact>
                    <Fact ok={item.contract_ok}>标准化契约已注册</Fact>
                    <Fact ok={item.reachable !== false}>
                      {item.reachable === null
                        ? '网络尚未探测'
                        : item.reachable
                          ? '端点网络可达'
                          : '端点网络不可达'}
                    </Fact>
                  </ul>
                  {item.notes !== undefined && item.notes.length > 0 ? (
                    <details className="source-notes">
                      <summary>配置说明</summary>
                      <ul>
                        {item.notes.map((note) => (
                          <li key={note}>{note}</li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                  {item.source === 'reddit' ? (
                    <div className="form-actions" style={{marginTop: 12}}>
                      <button
                        className="button"
                        type="button"
                        disabled={diagnostic.isPending || !item.enabled || !item.configured}
                        onClick={() => diagnostic.mutate('reddit')}
                      >
                        {diagnostic.isPending ? '正在验证…' : '验证 Reddit OAuth'}
                      </button>
                      {diagnostic.data?.source === 'reddit' ? (
                        <span className={`badge ${diagnostic.data.outcome === 'verified' ? 'success' : 'danger'}`}>
                          {diagnostic.data.outcome === 'verified' ? '凭据有效' : `验证失败：${diagnostic.data.outcome}`}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
