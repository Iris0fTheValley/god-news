import {X} from 'lucide-react';
import {useEffect, useRef} from 'react';

import {NAVIGATION_ITEMS} from '../app/navigation';

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
    items: NAVIGATION_ITEMS.flatMap((item) => (
      item.shortcut === undefined ? [] : [{label: item.label, keys: [item.shortcut]}]
    )),
  },
  {
    heading: '操作',
    items: [
      {label: '新建故事', keys: ['N']},
      {label: '焦点搜索', keys: ['/']},
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
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="shortcuts-dialog"
      aria-labelledby="shortcuts-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
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
    </dialog>
  );
}
