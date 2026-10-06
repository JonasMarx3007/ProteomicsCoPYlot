import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import LocalizationCutoffField from '../../src/components/LocalizationCutoffField';

const update = vi.hoisted(() => vi.fn());
vi.mock('../../src/lib/phosphoLocalization', () => ({
  usePhosphoLocalizationCutoff: () => ({ cutoff: 0.75, available: false, loaded: true, error: null, update }),
}));

it('allows clearing a retained cutoff after loading data without localization probabilities', () => {
  render(<LocalizationCutoffField />);
  const field = screen.getByLabelText('Localization probability cutoff') as HTMLInputElement;
  expect(field.disabled).toBe(false);
  fireEvent.change(field, { target: { value: '0' } });
  fireEvent.blur(field);
  expect(update).toHaveBeenCalledWith(0);
});
