import {
  Boxes,
  Clapperboard,
  Component,
  DatabaseZap,
  FolderOpen,
  Image as ImageIcon,
  LayoutTemplate,
  LibraryBig,
  Music,
  Rows3,
  UserCog,
  Wrench,
} from 'lucide-react';
import type {LucideIcon} from 'lucide-react';

export interface NavigationItem {
  to: string;
  label: string;
  shortLabel: string;
  description: string;
  icon: LucideIcon;
  shortcut?: string;
}

export interface NavigationGroup {
  label: string;
  items: NavigationItem[];
}

export interface NavigationSection {
  id: 'main' | 'library';
  label: string;
  description: string;
  icon: LucideIcon;
  groups: readonly NavigationGroup[];
}

const MAIN_GROUPS: readonly NavigationGroup[] = [
  {
    label: '编辑流程',
    items: [
      {
        to: '/stories',
        label: '故事队列',
        shortLabel: '故事',
        description: '筛选、审核并推进单条好消息',
        icon: Rows3,
        shortcut: '1',
      },
    ],
  },
  {
    label: '采集',
    items: [
      {
        to: '/collection/sources',
        label: '来源与就绪度',
        shortLabel: '来源',
        description: '检查配置、授权、契约与网络状态',
        icon: DatabaseZap,
        shortcut: '2',
      },
      {
        to: '/collection/runs',
        label: '采集运行',
        shortLabel: '采集',
        description: '启动、取消并追踪采集任务',
        icon: FolderOpen,
        shortcut: '3',
      },
    ],
  },
  {
    label: '节目制作',
    items: [
      {
        to: '/production/batches',
        label: '视频批次',
        shortLabel: '批次',
        description: '编排、审核并渲染横竖屏节目',
        icon: Clapperboard,
        shortcut: '4',
      },
    ],
  },
  {
    label: '系统',
    items: [
      {
        to: '/system/operations',
        label: '运维与留存',
        shortLabel: '运维',
        description: '查看调度、清理与操作历史',
        icon: Wrench,
        shortcut: '9',
      },
    ],
  },
] as const;

const LIBRARY_GROUPS: readonly NavigationGroup[] = [
  {
    label: '素材与角色',
    items: [
      {
        to: '/library/visual-assets',
        label: '视觉素材',
        shortLabel: '素材',
        description: '管理图片、视频、证据与使用权',
        icon: ImageIcon,
        shortcut: '5',
      },
      {
        to: '/library/roles',
        label: '角色与声音',
        shortLabel: '角色',
        description: '管理 Live2D、音色与情绪参考',
        icon: UserCog,
        shortcut: '6',
      },
      {
        to: '/library/audio',
        label: '音乐',
        shortLabel: '音乐',
        description: '检查本地背景音乐目录',
        icon: Music,
      },
    ],
  },
  {
    label: '视觉系统',
    items: [
      {
        to: '/visual/modules',
        label: '视觉模块',
        shortLabel: '模块',
        description: '检查生产模块、依赖与比例能力',
        icon: Component,
        shortcut: '7',
      },
      {
        to: '/visual/scene-lab',
        label: 'Scene Lab',
        shortLabel: 'Lab',
        description: '逐帧调试和验收生产 Remotion 场景',
        icon: LayoutTemplate,
        shortcut: '8',
      },
    ],
  },
] as const;

export const NAVIGATION_SECTIONS: readonly NavigationSection[] = [
  {
    id: 'main',
    label: '主功能',
    description: '采集、审核与节目生产',
    icon: Boxes,
    groups: MAIN_GROUPS,
  },
  {
    id: 'library',
    label: '素材库',
    description: '素材、角色与视觉模块',
    icon: LibraryBig,
    groups: LIBRARY_GROUPS,
  },
] as const;

export const NAVIGATION_GROUPS = NAVIGATION_SECTIONS.flatMap((section) => section.groups);
export const NAVIGATION_ITEMS = NAVIGATION_GROUPS.flatMap((group) => group.items);

export function navigationSectionForPath(pathname: string): NavigationSection {
  return NAVIGATION_SECTIONS.find((section) => section.groups.some((group) =>
    group.items.some(
      (item) => pathname === item.to || pathname.startsWith(`${item.to}/`),
    ),
  )) ?? NAVIGATION_SECTIONS[0];
}

export function navigationItemForPath(pathname: string): NavigationItem {
  return NAVIGATION_ITEMS.find(
    (item) => pathname === item.to || pathname.startsWith(`${item.to}/`),
  ) ?? NAVIGATION_ITEMS[0];
}
