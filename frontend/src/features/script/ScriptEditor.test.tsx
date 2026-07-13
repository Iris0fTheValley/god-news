import {screen, within} from '@testing-library/react';
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

  it('shares one role datalist, exposes scene transitions, and keeps visual hints out of the UI', () => {
    const {container} = renderWithApp(<ScriptEditor script={scriptFixture} onChange={vi.fn()} />);

    expect(container.querySelectorAll('datalist')).toHaveLength(1);
    expect(within(container).getAllByLabelText('过场')).toHaveLength(scriptFixture.segments.length);
    expect(within(container).getAllByText('画面 / 图片')).toHaveLength(scriptFixture.segments.length);
    expect(within(container).queryByText('雨伞和小狗')).not.toBeInTheDocument();
  });
});
