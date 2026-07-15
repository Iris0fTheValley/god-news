import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Pencil, Plus, Trash2} from 'lucide-react';
import {useState} from 'react';

import {createRole, deleteRole, listRoles, updateRole} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {
  EmotionReference,
  RoleProfile,
  RoleProfileCreate,
  RoleProfileReplace,
  RoleVisualAssets,
  SpeechEmotion,
} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {SPEECH_EMOTIONS, SPEECH_EMOTION_LABELS} from '../../components/narrationOptions';
import {useToast} from '../../components/toastContext';

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff\s_-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/[\u4e00-\u9fff]/g, (character) => {
      const code = character.codePointAt(0) ?? 0;
      return `u${code.toString(16)}`;
    })
    .replace(/^-+|-+$/g, '')
    .replace(/_/g, '-')
    .replace(/-{2,}/g, '-')
    || 'role';
}

function isSpeechEmotion(value: string): value is SpeechEmotion {
  return SPEECH_EMOTIONS.includes(value as SpeechEmotion);
}

function emptyEmotionRefs(): Record<SpeechEmotion, EmotionReference> {
  return Object.fromEntries(
    SPEECH_EMOTIONS.map((emotion) => [emotion, {audio_path: '', text: ''}]),
  ) as Record<SpeechEmotion, EmotionReference>;
}

function completeEmotionRefs(
  refs: Record<string, EmotionReference> | undefined,
): Record<SpeechEmotion, EmotionReference> {
  const initial = emptyEmotionRefs();
  for (const emotion of SPEECH_EMOTIONS) {
    const existing = refs?.[emotion];
    if (existing !== undefined) initial[emotion] = existing;
  }
  return initial;
}

interface RoleFormState {
  profileId: string | null;
  name: string;
  slug: string;
  kind: 'narrator' | 'host';
  speakerId: string;
  characterPrompt: string;
  visualAssets: RoleVisualAssets;
  gptWeightsPath: string;
  sovitsWeightsPath: string;
  ttsModelProfile: string;
  referenceLanguage: string;
  defaultSpokenLanguage: string;
  emotionRefs: Record<SpeechEmotion, EmotionReference>;
  defaultEmotion: string;
  defaultSpeed: number;
  defaultPitch: number;
  enabled: boolean;
  ttsEnabled: boolean;
  expectedVersion: number;
}

function emptyForm(): RoleFormState {
  return {
    profileId: null,
    name: '',
    slug: '',
    kind: 'narrator',
    speakerId: '',
    characterPrompt: '',
    visualAssets: {},
    gptWeightsPath: '',
    sovitsWeightsPath: '',
    ttsModelProfile: '',
    referenceLanguage: '',
    defaultSpokenLanguage: 'zh-CN',
    emotionRefs: emptyEmotionRefs(),
    defaultEmotion: 'happiness',
    defaultSpeed: 1,
    defaultPitch: 0,
    enabled: true,
    ttsEnabled: false,
    expectedVersion: 0,
  };
}

function formFromRole(role: RoleProfile): RoleFormState {
  return {
    profileId: role.profile_id ?? null,
    name: role.display_name,
    slug: role.slug,
    kind: role.kind,
    speakerId: role.speaker_id,
    characterPrompt: role.character_prompt,
    visualAssets: role.visual_assets ?? {},
    gptWeightsPath: role.gpt_weights_path ?? '',
    sovitsWeightsPath: role.sovits_weights_path ?? '',
    ttsModelProfile: role.tts_model_profile ?? '',
    referenceLanguage: role.reference_language ?? '',
    defaultSpokenLanguage: role.default_spoken_language,
    emotionRefs: completeEmotionRefs(role.emotion_refs),
    defaultEmotion: role.default_emotion,
    defaultSpeed: role.default_speed,
    defaultPitch: role.default_pitch,
    enabled: role.enabled,
    ttsEnabled: role.tts_enabled,
    expectedVersion: role.version,
  };
}

function validateAndBuildRole(
  form: RoleFormState,
): {body: RoleProfileCreate; error: string | null} {
  const gptWeightsPath = form.gptWeightsPath.trim();
  const sovitsWeightsPath = form.sovitsWeightsPath.trim();
  const ttsModelProfile = form.ttsModelProfile.trim();
  const populatedRefs: Record<string, EmotionReference> = {};

  for (const emotion of SPEECH_EMOTIONS) {
    const reference = form.emotionRefs[emotion];
    const audioPath = reference.audio_path.trim();
    const text = reference.text.trim();
    if ((audioPath === '') !== (text === '')) {
      return {body: {} as RoleProfileCreate, error: `「${SPEECH_EMOTION_LABELS[emotion]}」的参考音频与参考文本必须同时填写。`};
    }
    if (audioPath !== '') populatedRefs[emotion] = {audio_path: audioPath, text};
  }

  if (form.ttsEnabled) {
    if (!isSpeechEmotion(form.defaultEmotion)) {
      return {body: {} as RoleProfileCreate, error: '启用本地 TTS 的角色必须选择七种受支持情绪之一。'};
    }
    if (gptWeightsPath === '' || sovitsWeightsPath === '' || ttsModelProfile === '') {
      return {body: {} as RoleProfileCreate, error: '启用本地 TTS 时必须填写 GPT 权重、SoVITS 权重和模型配置。'};
    }
    if (Object.keys(populatedRefs).length !== SPEECH_EMOTIONS.length) {
      return {body: {} as RoleProfileCreate, error: '启用本地 TTS 时必须完整填写 7 种情绪的参考音频与参考文本。'};
    }
  }

  const body: RoleProfileCreate = {
    display_name: form.name.trim(),
    slug: form.slug || slugify(form.name),
    kind: form.kind,
    speaker_id: form.speakerId.trim() || form.slug || slugify(form.name),
    character_prompt: form.characterPrompt,
    default_emotion: form.defaultEmotion,
    default_spoken_language: form.defaultSpokenLanguage.trim(),
    default_speed: form.defaultSpeed,
    default_pitch: form.defaultPitch,
    visual_assets: form.visualAssets,
    enabled: form.enabled,
    tts_enabled: form.ttsEnabled,
  };
  if (gptWeightsPath !== '') body.gpt_weights_path = gptWeightsPath;
  if (sovitsWeightsPath !== '') body.sovits_weights_path = sovitsWeightsPath;
  if (ttsModelProfile !== '') body.tts_model_profile = ttsModelProfile;
  if (form.referenceLanguage.trim() !== '') body.reference_language = form.referenceLanguage.trim();
  if (Object.keys(populatedRefs).length > 0) body.emotion_refs = populatedRefs;
  return {body, error: null};
}

export function RolesPage() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [editing, setEditing] = useState<RoleFormState | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{id: string; version: number} | null>(null);

  const query = useQuery({
    queryKey: queryKeys.roles(),
    queryFn: () => listRoles(),
  });
  const invalidateRoles = () => void queryClient.invalidateQueries({queryKey: ['roles']});
  const createMutation = useMutation({
    mutationFn: createRole,
    onSuccess: () => {
      invalidateRoles();
      setEditing(null);
      pushToast({message: '角色已创建', durationMs: 3000});
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({id, body}: {id: string; body: RoleProfileReplace}) => updateRole(id, body),
    onSuccess: () => {
      invalidateRoles();
      setEditing(null);
      pushToast({message: '角色已更新', durationMs: 3000});
    },
  });
  const deleteMutation = useMutation({
    mutationFn: ({id, version}: {id: string; version: number}) => deleteRole(id, version),
    onSuccess: () => {
      invalidateRoles();
      setDeleteTarget(null);
      pushToast({message: '角色已停用', variant: 'caution', durationMs: 4000});
    },
  });

  const openCreate = () => {
    setFormError(null);
    setEditing(emptyForm());
  };
  const openEdit = (role: RoleProfile) => {
    setFormError(null);
    setEditing(formFromRole(role));
  };

  return (
    <div className="page roles-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CHARACTERS</p>
          <h1>角色管理</h1>
          <p>每个角色可复用一套 GPT/SoVITS 权重，并为 7 种情绪分别指定参考音频和参考文本。</p>
        </div>
        <button className="button primary" type="button" onClick={openCreate} disabled={editing !== null}>
          <Plus size={18} aria-hidden="true" /> 新建角色
        </button>
      </div>

      {query.isLoading ? (
        <div className="loading-state">正在加载角色列表…</div>
      ) : query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data !== undefined && query.data.length === 0 ? (
        <EmptyState title="尚未创建任何角色" description="创建一个播报人设，随后可在初审与脚本中选择。" action={{label: '新建角色', onClick: openCreate}} />
      ) : (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>名称</th><th>speaker_id</th><th>语音配置</th><th>语速 / 音高</th><th>状态</th><th className="actions-cell">操作</th>
              </tr>
            </thead>
            <tbody>
              {query.data?.map((role) => (
                <tr key={role.profile_id ?? role.slug}>
                  <td><strong>{role.display_name}</strong><br /><span className="metadata">{role.kind === 'host' ? '主持人' : '旁白'}</span></td>
                  <td className="metadata mono">{role.speaker_id}</td>
                  <td className="metadata">{role.tts_enabled ? `${Object.keys(role.emotion_refs ?? {}).length}/7 情绪参考` : '未启用本地 TTS'}</td>
                  <td className="metadata">{String(role.default_speed)}x / {String(role.default_pitch)}</td>
                  <td><span className={`badge ${role.enabled ? 'success' : 'muted'}`}>{role.enabled ? '已启用' : '已停用'}</span></td>
                  <td className="actions-cell">
                    <button className="icon-button" type="button" aria-label={`编辑 ${role.display_name}`} onClick={() => openEdit(role)}><Pencil size={16} aria-hidden="true" /></button>
                    <button
                      className="icon-button danger"
                      type="button"
                      aria-label={`停用 ${role.display_name}`}
                      disabled={role.profile_id === undefined || !role.enabled}
                      onClick={() => {
                        if (role.profile_id !== undefined) setDeleteTarget({id: role.profile_id, version: role.version});
                      }}
                    ><Trash2 size={16} aria-hidden="true" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing === null ? null : (
        <dialog className="create-drawer wide-drawer" open aria-labelledby="role-form-heading" onCancel={(event) => { event.preventDefault(); setEditing(null); }}>
          <div className="panel-header">
            <div><p className="eyebrow">{editing.profileId === null ? 'NEW ROLE' : 'EDIT ROLE'}</p><h2 id="role-form-heading">{editing.profileId === null ? '新建角色' : '编辑角色'}</h2></div>
            <button className="icon-button" type="button" onClick={() => setEditing(null)} aria-label="关闭">✕</button>
          </div>
          <form
            className="panel-body form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              const built = validateAndBuildRole(editing);
              if (built.error !== null) {
                setFormError(built.error);
                return;
              }
              setFormError(null);
              if (editing.profileId === null) createMutation.mutate(built.body);
              else updateMutation.mutate({id: editing.profileId, body: {...built.body, expected_version: editing.expectedVersion}});
            }}
          >
            <label className="field wide">
              <span>显示名称</span>
              <input
                className="input"
                required
                value={editing.name}
                onChange={(event) => {
                  const name = event.target.value;
                  const nextSlug = editing.profileId === null ? slugify(name) : editing.slug;
                  const speakerWasAuto = editing.speakerId === '' || editing.speakerId === editing.slug;
                  setEditing({...editing, name, slug: nextSlug, speakerId: editing.profileId === null && speakerWasAuto ? nextSlug : editing.speakerId});
                }}
              />
              <small>{editing.profileId === null ? `slug 将创建为 ${editing.slug || 'role'}` : `slug 固定为 ${editing.slug}`}</small>
            </label>
            <label className="field"><span>角色类型</span><select className="select" value={editing.kind} onChange={(event) => setEditing({...editing, kind: event.target.value as RoleFormState['kind']})}><option value="narrator">旁白</option><option value="host">主持人</option></select></label>
            <label className="field"><span>speaker_id</span><input className="input mono" required value={editing.speakerId} onChange={(event) => setEditing({...editing, speakerId: event.target.value})} /></label>
            <label className="field wide"><span>角色描述（Prompt）</span><textarea className="textarea compact" value={editing.characterPrompt} onChange={(event) => setEditing({...editing, characterPrompt: event.target.value})} /></label>
            <label className="field wide"><span>Live2D 模型路径</span><input className="input mono" placeholder="live2d_models/3.model.json" value={editing.visualAssets.live2d_asset_ref ?? ''} onChange={(event) => setEditing({...editing, visualAssets: {...editing.visualAssets, live2d_asset_ref: event.target.value || null}})} /></label>

            <fieldset className="field-group wide">
              <legend className="eyebrow">LOCAL GPT-SOVITS</legend>
              <p className="field-hint">同一角色的 7 种情绪只切换参考音频与文本；权重不随段落更换。</p>
              <div className="form-grid">
                <label className="checkbox-field"><input type="checkbox" checked={editing.ttsEnabled} onChange={(event) => setEditing({...editing, ttsEnabled: event.target.checked})} /><span>启用本地 TTS</span></label>
                <label className="checkbox-field"><input type="checkbox" checked={editing.enabled} onChange={(event) => setEditing({...editing, enabled: event.target.checked})} /><span>允许新脚本选择此角色</span></label>
                <label className="field"><span>GPT 权重路径</span><input className="input mono" placeholder="…/model.ckpt" value={editing.gptWeightsPath} onChange={(event) => setEditing({...editing, gptWeightsPath: event.target.value})} /></label>
                <label className="field"><span>SoVITS 权重路径</span><input className="input mono" placeholder="…/model.pth" value={editing.sovitsWeightsPath} onChange={(event) => setEditing({...editing, sovitsWeightsPath: event.target.value})} /></label>
                <label className="field"><span>TTS 模型配置</span><input className="input mono" placeholder="v2Pro" value={editing.ttsModelProfile} onChange={(event) => setEditing({...editing, ttsModelProfile: event.target.value})} /></label>
                <label className="field"><span>参考文本语言</span><input className="input mono" placeholder="all_zh / all_ja（可选）" value={editing.referenceLanguage} onChange={(event) => setEditing({...editing, referenceLanguage: event.target.value})} /></label>
                <label className="field"><span>默认口播语言</span><input className="input mono" required placeholder="zh-CN / en-US / ja-JP" value={editing.defaultSpokenLanguage} onChange={(event) => setEditing({...editing, defaultSpokenLanguage: event.target.value})} /></label>
                <label className="field"><span>默认情绪</span><select className="select" value={editing.defaultEmotion} onChange={(event) => setEditing({...editing, defaultEmotion: event.target.value})}>{!isSpeechEmotion(editing.defaultEmotion) ? <option value={editing.defaultEmotion}>保留历史值：{editing.defaultEmotion}</option> : null}{SPEECH_EMOTIONS.map((emotion) => <option key={emotion} value={emotion}>{SPEECH_EMOTION_LABELS[emotion]}</option>)}</select></label>
                <label className="field"><span>默认语速</span><input className="input" type="number" min={0.6} max={1.65} step={0.05} value={editing.defaultSpeed} onChange={(event) => setEditing({...editing, defaultSpeed: Number(event.target.value)})} /></label>
                <label className="field"><span>默认音高</span><input className="input" type="number" min={-12} max={12} step={0.5} value={editing.defaultPitch} onChange={(event) => setEditing({...editing, defaultPitch: Number(event.target.value)})} /></label>
              </div>
            </fieldset>

            <fieldset className="field-group wide">
              <legend className="eyebrow">7 EMOTION REFERENCES</legend>
              <p className="field-hint">DSakiko 参考音频配置可直接填写到对应行。启用本地 TTS 时必须完整配置。</p>
              {SPEECH_EMOTIONS.map((emotion) => {
                const reference = editing.emotionRefs[emotion];
                return (
                  <div className="form-grid" key={emotion}>
                    <p className="field-hint" style={{alignSelf: 'end', marginBottom: 10}}>{SPEECH_EMOTION_LABELS[emotion]} <span className="metadata">{emotion}</span></p>
                    <label className="field"><span>参考音频路径</span><input className="input mono" value={reference.audio_path} onChange={(event) => setEditing({...editing, emotionRefs: {...editing.emotionRefs, [emotion]: {...reference, audio_path: event.target.value}}})} /></label>
                    <label className="field"><span>参考文本</span><input className="input" value={reference.text} onChange={(event) => setEditing({...editing, emotionRefs: {...editing.emotionRefs, [emotion]: {...reference, text: event.target.value}}})} /></label>
                  </div>
                );
              })}
            </fieldset>

            {formError === null ? null : <div className="error-banner wide">{formError}</div>}
            {(createMutation.error ?? updateMutation.error) === null ? null : <div className="wide"><ApiErrorNotice error={(createMutation.error ?? updateMutation.error)!} /></div>}
            <div className="form-actions wide"><button className="button" type="button" onClick={() => setEditing(null)}>取消</button><button className="button primary" type="submit" disabled={createMutation.isPending || updateMutation.isPending}>{createMutation.isPending || updateMutation.isPending ? '保存中…' : '保存角色'}</button></div>
          </form>
        </dialog>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="停用角色"
        message="停用后，新脚本不能再选择此角色；既有故事、脚本与成片会保留历史引用。"
        variant="danger"
        confirmLabel="确认停用"
        onConfirm={() => { if (deleteTarget !== null) deleteMutation.mutate(deleteTarget); }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
