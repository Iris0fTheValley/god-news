import {X} from 'lucide-react';

interface ShortcutDef {
  label: string;
  keys: string[];
}

interface ShortcutGroup {
  heading: string;
  items: ShortcutDef[];
}

const GLOBAL_SHORTCUTS: ShortcutGroup[] = [
  {
    heading: '导航',
    items: [
      {label: '故事队列', keys: ['1']},
      {label: '来源运行', keys: ['2']},
      {label: '角色管理', keys: ['3']},
      {label: '视频批次', keys: ['4']},
      {label: '采集运行', keys: ['5']},
      {label: '运维日志', keys: ['6']},
      {label: 'BGM 管理', keys: ['7']},
    ],
  },
  {
    heading: '操作',
    items: [
      {label: '新建故事', keys: ['N']},
      {label: '焦点搜索', keys: ['/']},
      {label: '批准当前审核', keys: ['Ctrl', 'Enter']},
      {label: '退回修改', keys: ['Ctrl', 'Shift', 'Enter']},
      {label: '关闭弹窗/对话框', keys: ['Esc']},
    ],
  },
  {
    heading: '脚本编辑',
    items: [
      {label: '撤销修改', keys: ['Ctrl', 'Z']},
      {label: '重做修改', keys: ['Ctrl', 'Shift', 'Z']},
    ],
  },
];

interface KeyboardShortcutsProps {
  open: boolean;
  onClose: () => void;
}

export function KeyboardShortcuts({open, onClose}: KeyboardShortcutsProps) {
  if (!open) return null;

  return (
    <div
      className="shortcuts-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcuts-title"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose();
      }}
    >
      <div
        className="shortcuts-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-header">
          <div>
            <p className="eyebrow">KEYBOARD</p>
            <h2 id="shortcuts-title">快捷键参考</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            aria-label="关闭"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="panel-body" style={{padding: 0}}>
          {GLOBAL_SHORTCUTS.map((group) => (
            <div className="shortcuts-section" key={group.heading}>
              <h3>{group.heading}</h3>
              {group.items.map((item) => (
                <div className="shortcut-row" key={item.label}>
                  <span>{item.label}</span>
                  <kbd>
                    {item.keys.map((key, i) => (
                      <span key={key}>
                        {i > 0 ? ' + ' : ''}
                        {key}
                      </span>
                    ))}
                  </kbd>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
