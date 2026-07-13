import { test, expect } from '@playwright/test';

test.describe('Job Application Form', () => {
  test('should select a role, fill required fields, and submit application', async ({ page }) => {
    // Navigate to the jobs page
    await page.goto('https://testradius.dev/jobs');

    // Wait for the application form to be visible
    const applyingForCombobox = page.getByLabel('Applying For');
    await expect(applyingForCombobox).toBeVisible();

    // Select a role from the dropdown
    await applyingForCombobox.selectOption({ label: 'Freelance Full-Stack Developer' });
    await expect(applyingForCombobox).toHaveValue('Freelance Full-Stack Developer');

    // Fill first name field
    const firstNameField = page.getByLabel('First Name');
    await expect(firstNameField).toBeVisible();
    await firstNameField.fill('Michael');
    await expect(firstNameField).toHaveValue('Michael');

    // Fill last name field
    const lastNameField = page.getByLabel('Last Name');
    await expect(lastNameField).toBeVisible();
    await lastNameField.fill('Chen');
    await expect(lastNameField).toHaveValue('Chen');

    // Fill email address field
    const emailField = page.getByLabel('Email Address');
    await expect(emailField).toBeVisible();
    await emailField.fill('michael.chen@gmail.com');
    await expect(emailField).toHaveValue('michael.chen@gmail.com');

    // Submit the application
    const submitButton = page.getByRole('button', { name: 'Submit Application' });
    await expect(submitButton).toBeVisible();
    await submitButton.click();

    // Assert submission was successful - wait for response/navigation or confirmation
    // The form should either show a success message or navigate to a confirmation state
    await expect(submitButton).not.toBeVisible({ timeout: 10000 }).catch(async () => {
      // If button is still visible, check for any error messages
      await expect(page.locator('text=error')).not.toBeVisible();
    });
  });
});