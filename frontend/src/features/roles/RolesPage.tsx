import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Pencil, Plus, Trash2} from 'lucide-react';
import {useState} from 'react';

import {createRole, deleteRole, listRoles, updateRole} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {RoleProfileCreate, RoleProfileReplace, RoleVisualAssets} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/toastContext';

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff\s_-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/[\u4e00-\u9fff]/g, (ch) => {
      const code = ch.codePointAt(0) ?? 0;
      return `u${code.toString(16)}`;
    })
    .replace(/^-+|-+$/g, '')
    .replace(/_/g, '-')
    .replace(/-{2,}/g, '-')
    || 'role';
}

interface RoleFormState {
  profileId: string | null;
  name: string;
  kind: 'narrator' | 'host';
  speakerId: string;
  gptWeightsPath: string;
  sovitsWeightsPath: string;
  visualAssets: RoleVisualAssets;
  defaultSpeed: number;
  defaultPitch: number;
  enabled: boolean;
  expectedVersion: number;
}

function emptyForm(): RoleFormState {
  return {
    profileId: null,
    name: '',
    kind: 'narrator',
    speakerId: '',
    gptWeightsPath: '',
    sovitsWeightsPath: '',
    visualAssets: {},
    defaultSpeed: 1,
    defaultPitch: 0,
    enabled: true,
    expectedVersion: 0,
  };
}

export function RolesPage() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [editing, setEditing] = useState<RoleFormState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{id: string; version: number} | null>(null);

  const query = useQuery({
    queryKey: queryKeys.roles(),
    queryFn: () => listRoles(),
  });
  const createMutation = useMutation({
    mutationFn: createRole,
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.roles()});
      setEditing(null);
      pushToast({message: '角色已创建', durationMs: 3000});
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({id, body}: {id: string; body: RoleProfileReplace}) => updateRole(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.roles()});
      setEditing(null);
      pushToast({message: '角色已更新', durationMs: 3000});
    },
  });
  const deleteMutation = useMutation({
    mutationFn: ({id, version}: {id: string; version: number}) => deleteRole(id, version),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.roles()});
      setDeleteTarget(null);
      pushToast({
        message: '角色已停用',
        variant: 'caution',
        durationMs: 5000,
        action: {label: '说明', onClick: () => pushToast({message: '角色已软停用，历史脚本与成片仍保留引用。', variant: 'caution', durationMs: 3000})},
      });
    },
  });

  return (
    <div className="page roles-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CHARACTERS</p>
          <h1>角色管理</h1>
          <p>管理旁白与主持人的人设配置——TTS 权重路径、语速音高。角色数据将被脚本编辑器和视频批次引用。</p>
        </div>
        <button
          className="button primary"
          type="button"
          onClick={() => setEditing(emptyForm())}
          disabled={editing !== null}
        >
          <Plus size={18} aria-hidden="true" /> 新建角色
        </button>
      </div>

      {query.isLoading ? (
        <div className="loading-state">正在加载角色列表…</div>
      ) : query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data !== undefined && query.data.length === 0 ? (
        <EmptyState
          title="尚未创建任何角色"
          description="点击「新建角色」创建一个播报人设。"
          action={{label: '新建角色', onClick: () => setEditing(emptyForm())}}
        />
      ) : (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>名称</th>
                <th>GPT 权重</th>
                <th>SoVITS 权重</th>
                <th>语速 / 音高</th>
                <th>状态</th>
                <th className="actions-cell">操作</th>
              </tr>
            </thead>
            <tbody>
              {query.data?.map((role) => (
                <tr key={role.profile_id ?? role.slug}>
                  <td><strong>{role.display_name}</strong></td>
                  <td className="metadata file-path-cell" title={role.gpt_weights_path ?? ''}>{role.gpt_weights_path ?? '—'}</td>
                  <td className="metadata file-path-cell" title={role.sovits_weights_path ?? ''}>{role.sovits_weights_path ?? '—'}</td>
                  <td className="metadata">
                    {String(role.default_speed)}x / {String(role.default_pitch)}
                  </td>
                  <td>
                    <span className={`badge ${role.enabled ? 'success' : 'muted'}`}>
                      {role.enabled ? '已启用' : '已停用'}
                    </span>
                  </td>
                  <td className="actions-cell">
                    <button
                      className="icon-button"
                      type="button"
                      aria-label={`编辑 ${role.display_name}`}
                      onClick={() => setEditing({
                        profileId: role.profile_id ?? null,
                        name: role.display_name,
                        kind: role.kind,
                        speakerId: role.speaker_id,
                        gptWeightsPath: role.gpt_weights_path ?? '',
                        sovitsWeightsPath: role.sovits_weights_path ?? '',
                        visualAssets: role.visual_assets ?? {},
                        defaultSpeed: role.default_speed,
                        defaultPitch: role.default_pitch,
                        enabled: role.enabled,
                        expectedVersion: role.version,
                      })}
                    >
                      <Pencil size={16} aria-hidden="true" />
                    </button>
                    <button
                      className="icon-button danger"
                      type="button"
                      aria-label={`停用 ${role.display_name}`}
                      disabled={role.profile_id === undefined || !role.enabled}
                      onClick={() => {
                        if (role.profile_id !== undefined) {
                          setDeleteTarget({id: role.profile_id, version: role.version});
                        }
                      }}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Role edit/create drawer */}
      {editing !== null ? (
        <dialog
          className="create-drawer"
          open
          aria-labelledby="role-form-heading"
          onCancel={(e) => { e.preventDefault(); setEditing(null); }}
        >
          <div className="panel-header">
            <div>
              <p className="eyebrow">{editing.profileId !== null ? 'EDIT ROLE' : 'NEW ROLE'}</p>
              <h2 id="role-form-heading">{editing.profileId !== null ? '编辑角色' : '新建角色'}</h2>
            </div>
            <button className="icon-button" type="button" onClick={() => setEditing(null)} aria-label="关闭">✕</button>
          </div>
          <form
            className="panel-body form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              const body: RoleProfileCreate = {
                display_name: editing.name,
                slug: slugify(editing.name),
                kind: editing.kind,
                speaker_id: editing.speakerId.trim() || slugify(editing.name),
                default_emotion: 'neutral',
                default_speed: editing.defaultSpeed,
                default_pitch: editing.defaultPitch,
                visual_assets: editing.visualAssets,
                enabled: editing.enabled,
              };
              if (editing.gptWeightsPath.trim() !== '') body.gpt_weights_path = editing.gptWeightsPath.trim();
              if (editing.sovitsWeightsPath.trim() !== '') body.sovits_weights_path = editing.sovitsWeightsPath.trim();
              if (editing.profileId !== null) {
                updateMutation.mutate({
                  id: editing.profileId,
                  body: {...body, expected_version: editing.expectedVersion},
                });
              } else {
                createMutation.mutate(body);
              }
            }}
          >
            <label className="field wide">
              <span>显示名称</span>
              <input className="input" required value={editing.name} onChange={(e) => setEditing({...editing, name: e.target.value})} />
            </label>
            <label className="field">
              <span>角色类型</span>
              <select
                className="select"
                value={editing.kind}
                onChange={(e) => setEditing({...editing, kind: e.target.value as RoleFormState['kind']})}
              >
                <option value="narrator">旁白</option>
                <option value="host">主持人</option>
              </select>
            </label>
            <label className="field">
              <span>TTS speaker_id</span>
              <input
                className="input mono"
                placeholder="narrator"
                value={editing.speakerId}
                onChange={(e) => setEditing({...editing, speakerId: e.target.value})}
              />
            </label>
            <fieldset className="field-group wide">
              <legend className="eyebrow">TTS 语音模型权重</legend>
              <p className="field-hint">当前后端仅支持单一语音实例。多角色独立权重需后端改造（见交接文档）。</p>
              <label className="field">
                <span>GPT 权重路径</span>
                <input
                  className="input mono"
                  placeholder="J:\models\gpt-narrator.pth"
                  value={editing.gptWeightsPath}
                  onChange={(e) => setEditing({...editing, gptWeightsPath: e.target.value})}
                />
              </label>
              <label className="field">
                <span>SoVITS 权重路径</span>
                <input
                  className="input mono"
                  placeholder="J:\models\sovits-narrator.pth"
                  value={editing.sovitsWeightsPath}
                  onChange={(e) => setEditing({...editing, sovitsWeightsPath: e.target.value})}
                />
              </label>
            </fieldset>
            <label className="field">
              <span>默认语速</span>
              <input className="input" type="number" min={0.6} max={1.65} step={0.05} value={editing.defaultSpeed} onChange={(e) => setEditing({...editing, defaultSpeed: Number(e.target.value)})} />
            </label>
            <label className="field">
              <span>默认音高</span>
              <input className="input" type="number" min={-12} max={12} step={0.5} value={editing.defaultPitch} onChange={(e) => setEditing({...editing, defaultPitch: Number(e.target.value)})} />
            </label>
            <label className="checkbox-field">
              <input type="checkbox" checked={editing.enabled} onChange={(e) => setEditing({...editing, enabled: e.target.checked})} />
              <span>启用此角色</span>
            </label>
            {(createMutation.error ?? updateMutation.error) !== null ? (
              <div className="wide">
                <ApiErrorNotice error={(createMutation.error ?? updateMutation.error)!} />
              </div>
            ) : null}
            <div className="form-actions wide">
              <button className="button" type="button" onClick={() => setEditing(null)}>取消</button>
              <button className="button primary" type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                {createMutation.isPending || updateMutation.isPending ? '保存中…' : '保存'}
              </button>
            </div>
          </form>
        </dialog>
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="停用角色"
        message="停用后，新任务不能再选择此角色；既有故事、脚本与成片会保留历史引用。"
        variant="danger"
        confirmLabel="确认停用"
        onConfirm={() => {
          if (deleteTarget !== null) deleteMutation.mutate(deleteTarget);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
