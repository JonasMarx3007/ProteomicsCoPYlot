import { test, expect } from '@playwright/test';

for (const entry of ['typing', 'pasting']) {
  for (const commit of ['Enter', 'blur']) {
    test(`${entry} numbers and committing with ${commit} preserves decimal commas and refuses ambiguous separators`, async ({ page, context }) => {
      await context.grantPermissions(['clipboard-read', 'clipboard-write']);
      await page.goto('/tests/browser/fixtures/numberField.html');
      const input = page.getByLabel('Maximum term size');
      const applied = page.getByLabel('Applied value');
      const enter = async text => {
        await input.fill('');
        if (entry === 'typing') {
          await input.pressSequentially(text);
        } else {
          await page.evaluate(text => navigator.clipboard.writeText(text), text);
          await input.press('ControlOrMeta+V');
        }
        await expect(input).toHaveValue(text);
      };
      const apply = async () => {
        if (commit === 'Enter') await input.press('Enter');
        else await page.getByRole('button', { name: 'Leave field' }).click();
      };
      let previous = '500';
      for (const [text, value] of [
        ['1000', '1000'], ['0.05', '0.05'], ['0,05', '0.05'],
        ['1,5', '1.5'], ['0,001', '0.001'], ['1.234', '1.234'],
        ['-0,001', '-0.001'], ['1,25e-2', '0.0125'],
      ]) {
        await enter(text);
        await expect(applied).toHaveText(previous);
        await apply();
        await expect(applied).toHaveText(value);
        await expect(input).toHaveValue(value);
        await expect(page.getByRole('alert')).toHaveCount(0);
        previous = value;
      }
      for (const text of ['1,000', '1,234', '-1,000', '1234,567', '1,000e2', '1,234.56', '1.234,56', '1,000,000', '1 000', 'invalid']) {
        await enter(text);
        await apply();
        await expect(applied).toHaveText(previous);
        await expect(input).toHaveValue(text);
        await expect(input).toHaveAttribute('aria-invalid', 'true');
        await expect(page.getByRole('alert')).toContainText('without thousands separators');
      }
      await enter('1000');
      await apply();
      await expect(applied).toHaveText('1000');
      await expect(input).not.toHaveAttribute('aria-invalid');
      await expect(page.getByRole('alert')).toHaveCount(0);
      await enter('1,000');
      await apply();
      await page.getByRole('button', { name: 'External update' }).click();
      await expect(input).toHaveValue('600');
      await expect(page.getByRole('alert')).toHaveCount(0);
    });
  }
}
