import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';

import {scriptFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {ScriptEditor} from './ScriptEditor';

describe('ScriptEditor', () => {
  it('reorders segments while restoring a contiguous sequence', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithApp(<ScriptEditor script={scriptFixture} onChange={onChange} />);

    await user.click(screen.getByRole('button', {name: '上移第 2 段'}));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      segments: [
        expect.objectContaining({text: '但有人停下了脚步。', sequence: 0}),
        expect.objectContaining({text: '雨下得很大。', sequence: 1}),
      ],
    }));
  });
});
