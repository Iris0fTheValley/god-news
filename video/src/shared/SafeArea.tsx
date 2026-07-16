import type {ReactNode} from 'react';

import type {Rect} from '../layout/compile-layout';
import {rectStyle} from '../layout/compile-layout';

export const SafeArea = ({
  rect,
  children,
}: {
  rect: Rect;
  children: ReactNode;
}) => (
  <div
    data-safe-area
    style={{
      position: 'absolute',
      ...rectStyle(rect),
    }}
  >
    {children}
  </div>
);
