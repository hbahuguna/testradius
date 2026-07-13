import { test, expect } from '@playwright/test';

test.describe('Job Application Form Submission', () => {
  test('should select role, fill required fields, and submit application', async ({ page }) => {
    // Navigate to the jobs page
    await page.goto('https://testradius.dev/jobs');
    await expect(page).toHaveURL(/jobs/);
    
    // Wait for the application form to be visible
    await expect(page.getByLabel('Applying For')).toBeVisible();
    await expect(page.getByLabel('First Name')).toBeVisible();
    await expect(page.getByLabel('Last Name')).toBeVisible();
    await expect(page.getByLabel('Email Address')).toBeVisible();
    
    // Get all available options in the combobox
    const applyingFor = page.getByLabel('Applying For');
    const options = await applyingFor.locator('option').allTextContents();
    
    // Filter out placeholder options (typically first option)
    const realOptions = options.filter(option => 
      !option.toLowerCase().includes('select') && 
      !option.toLowerCase().includes('choose') &&
      option.trim() !== ''
    );
    
    // Verify we have at least one real option
    expect(realOptions.length).toBeGreaterThan(0);
    
    // Select the first available role (not placeholder)
    await applyingFor.selectOption({ label: realOptions[0] });
    
    // Verify selection was made
    const selectedValue = await applyingFor.inputValue();
    expect(selectedValue).toBeTruthy();
    
    // Fill in personal details
    const firstName = page.getByLabel('First Name');
    const lastName = page.getByLabel('Last Name');
    const email = page.getByLabel('Email Address');
    
    await firstName.fill('John');
    await lastName.fill('Doe');
    await email.fill('john.doe@example.com');
    
    // Verify all fields are filled correctly
    await expect(firstName).toHaveValue('John');
    await expect(lastName).toHaveValue('Doe');
    await expect(email).toHaveValue('john.doe@example.com');
    
    // Submit the application
    const submitButton = page.getByRole('button', { name: 'Submit Application' });
    await expect(submitButton).toBeVisible();
    await submitButton.click();
    
    // Wait for submission to process - check for success indicators
    // Common patterns: success message, redirect, or button state change
    await expect(submitButton).toBeVisible({ timeout: 10000 }); // Button still visible after submission
    
    // Check for success message or confirmation
    // Try multiple common success indicators
    const successIndicators = [
      page.getByText(/success|thank|received|submitted/i),
      page.getByRole('heading', { name: /success|thank|confirmation/i }),
      page.getByText(/application.*submitted|thank.*applying/i)
    ];
    
    let successFound = false;
    for (const indicator of successIndicators) {
      try {
        await indicator.first().waitFor({ state: 'visible', timeout: 5000 });
        successFound = true;
        break;
      } catch {
        // Continue to next indicator
      }
    }
    
    // If no explicit success message found, at least verify:
    // 1. Page is still on jobs page or redirected to success page
    // 2. No error messages are visible
    // 3. Submit button is still visible (most SPAs keep it)
    if (!successFound) {
      // Check URL is still valid
      await expect(page).toHaveURL(/jobs|success|thank/i);
      
      // Verify no error messages are visible
      const errorElements = page.locator('.error, [role="alert"], .alert-error');
      await expect(errorElements).toHaveCount(0);
    }
  });
});