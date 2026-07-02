#!/usr/bin/env python3
"""Generate training dataset for SDET model in Unsloth format.

Each example: (existing repo page objects + feature description) → (Playwright test code)

Output: JSONL file with messages array (Qwen3/Unsloth chat format).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PageObjectTemplate:
    class_name: str
    file_import: str
    selectors: Dict[str, str]
    methods: List[str]
    url_path: Optional[str] = None


@dataclass
class UtilityTemplate:
    name: str
    file_import: str
    signature: str
    description: str


@dataclass
class TestExample:
    description: str
    feature_type: str
    test_type: str
    page_objects: List[PageObjectTemplate]
    utilities: List[UtilityTemplate]
    choose_between_utility_and_raw: bool = False
    code: str = ""
    explanation: str = ""


PAGE_OBJECTS = {
    "LoginPage": PageObjectTemplate(
        class_name="LoginPage",
        file_import="../pages/LoginPage",
        selectors={
            "emailInput": "page.getByLabel('Email address')",
            "passwordInput": "page.getByLabel('Password')",
            "loginButton": "page.getByRole('button', { name: /sign in/i })",
            "errorMessage": "page.getByTestId('login-error')",
            "rememberMe": "page.getByRole('checkbox', { name: /remember/i })",
            "forgotPassword": "page.getByRole('link', { name: /forgot/i })",
        },
        methods=["goto()", "fillCredentials(email, password)", "submit()", "login(email, password)"],
        url_path="/login",
    ),
    "DashboardPage": PageObjectTemplate(
        class_name="DashboardPage",
        file_import="../pages/DashboardPage",
        selectors={
            "userGreeting": "page.getByTestId('user-greeting')",
            "logoutButton": "page.getByRole('button', { name: /log out/i })",
            "navSidebar": "page.locator('nav.sidebar')",
            "profileLink": "page.getByRole('link', { name: /profile/i })",
            "searchInput": "page.getByPlaceholder('Search...')",
            "notificationsBadge": "page.getByTestId('notification-count')",
        },
        methods=["logout()", "search(query)"],
    ),
    "ProfilePage": PageObjectTemplate(
        class_name="ProfilePage",
        file_import="../pages/ProfilePage",
        selectors={
            "nameInput": "page.getByLabel('Full name')",
            "emailInput": "page.getByLabel('Email address')",
            "saveButton": "page.getByRole('button', { name: /save/i })",
            "avatarUpload": "page.locator('input[type=\"file\"]')",
            "cancelButton": "page.getByRole('link', { name: /cancel/i })",
            "successMessage": "page.getByTestId('save-success')",
        },
        methods=["goto()", "updateProfile(name, email)"],
        url_path="/profile",
    ),
    "SignupPage": PageObjectTemplate(
        class_name="SignupPage",
        file_import="../pages/SignupPage",
        selectors={
            "nameInput": "page.getByLabel('Full name')",
            "emailInput": "page.getByLabel('Email')",
            "passwordInput": "page.getByLabel('Create password')",
            "confirmInput": "page.getByLabel('Confirm password')",
            "submitButton": "page.getByRole('button', { name: /create account/i })",
            "termsCheckbox": "page.getByRole('checkbox', { name: /terms/i })",
            "successMessage": "page.getByTestId('signup-success')",
        },
        methods=["goto()", "fillForm(name, email, password)", "submit()"],
        url_path="/signup",
    ),
    "SearchResultsPage": PageObjectTemplate(
        class_name="SearchResultsPage",
        file_import="../pages/SearchResultsPage",
        selectors={
            "resultsList": "page.getByTestId('search-results')",
            "resultItems": "page.locator('[data-testid=\"result-item\"]')",
            "noResultsMessage": "page.getByTestId('no-results')",
            "filterDropdown": "page.getByLabel('Filter by')",
            "sortSelect": "page.getByLabel('Sort by')",
            "pagination": "page.locator('nav.pagination')",
        },
        methods=["goto(query)", "applyFilter(filter)", "sortBy(option)"],
        url_path="/search",
    ),
    "SettingsPage": PageObjectTemplate(
        class_name="SettingsPage",
        file_import="../pages/SettingsPage",
        selectors={
            "themeSelect": "page.getByLabel('Theme')",
            "languageSelect": "page.getByLabel('Language')",
            "notificationsToggle": "page.getByRole('switch', { name: /notifications/i })",
            "saveButton": "page.getByRole('button', { name: /save settings/i })",
            "successMessage": "page.getByTestId('settings-saved')",
        },
        methods=["goto()", "updateSetting(label, value)"],
        url_path="/settings",
    ),
    "PaymentPage": PageObjectTemplate(
        class_name="PaymentPage",
        file_import="../pages/PaymentPage",
        selectors={
            "cardInput": "page.getByPlaceholder('Card number')",
            "expiryInput": "page.getByPlaceholder('MM/YY')",
            "cvvInput": "page.getByPlaceholder('CVV')",
            "nameOnCard": "page.getByLabel('Name on card')",
            "payButton": "page.getByRole('button', { name: /pay/i })",
            "errorMessage": "page.getByTestId('payment-error')",
            "successMessage": "page.getByTestId('payment-success')",
        },
        methods=["goto()", "fillCardDetails(card, expiry, cvv, name)", "pay()"],
        url_path="/payment",
    ),
    "AdminUserListPage": PageObjectTemplate(
        class_name="AdminUserListPage",
        file_import="../pages/AdminUserListPage",
        selectors={
            "userTable": "page.locator('table.users')",
            "searchInput": "page.getByPlaceholder('Search users...')",
            "addUserButton": "page.getByRole('button', { name: /add user/i })",
            "deleteButton": "page.getByRole('button', { name: /delete/i })",
            "confirmDelete": "page.getByRole('button', { name: /confirm/i })",
            "successMessage": "page.getByTestId('action-success')",
        },
        methods=["goto()", "searchUser(query)", "deleteUser(email)"],
        url_path="/admin/users",
    ),
}

UTILITIES = {
    "loginAs": UtilityTemplate(
        name="loginAs",
        file_import="../utils/auth",
        signature="loginAs(page: Page, email: string, password: string): Promise<void>",
        description="Fills credentials, clicks sign in, waits for dashboard URL",
    ),
    "logout": UtilityTemplate(
        name="logout",
        file_import="../utils/auth",
        signature="logout(page: Page): Promise<void>",
        description="Clicks logout button, waits for login URL",
    ),
    "waitForPageLoad": UtilityTemplate(
        name="waitForPageLoad",
        file_import="../utils/navigation",
        signature="waitForPageLoad(page: Page): Promise<void>",
        description="Waits for networkidle load state",
    ),
    "navigateAndVerify": UtilityTemplate(
        name="navigateAndVerify",
        file_import="../utils/navigation",
        signature="navigateAndVerify(page: Page, url: string, headingPattern: RegExp): Promise<void>",
        description="Navigates to URL and verifies page heading matches pattern",
    ),
    "generateRandomEmail": UtilityTemplate(
        name="generateRandomEmail",
        file_import="../utils/navigation",
        signature="generateRandomEmail(): string",
        description="Generates a random email for test data",
    ),
    "generateRandomString": UtilityTemplate(
        name="generateRandomString",
        file_import="../utils/data",
        signature="generateRandomString(length: number): string",
        description="Generates a random alphanumeric string of given length",
    ),
    "uploadFile": UtilityTemplate(
        name="uploadFile",
        file_import="../utils/upload",
        signature="uploadFile(page: Page, selector: string, filePath: string): Promise<void>",
        description="Uploads a file using the given file input selector",
    ),
    "captureScreenshot": UtilityTemplate(
        name="captureScreenshot",
        file_import="../utils/debug",
        signature="captureScreenshot(page: Page, name: string): Promise<void>",
        description="Takes a screenshot and saves to test artifacts directory",
    ),
    "clearAndFill": UtilityTemplate(
        name="clearAndFill",
        file_import="../utils/forms",
        signature="clearAndFill(locator: Locator, value: string): Promise<void>",
        description="Clears the input field then fills with the given value",
    ),
    "dismissDialog": UtilityTemplate(
        name="dismissDialog",
        file_import="../utils/dialogs",
        signature="dismissDialog(page: Page, accept: boolean): Promise<void>",
        description="Listens for the next dialog and accepts or dismisses it",
    ),
}


SCENARIO_TEMPLATES = [
    {
        "description": "Login with valid credentials",
        "feature_type": "auth",
        "test_type": "positive",
        "page_objects": ["LoginPage", "DashboardPage"],
        "utilities": ["loginAs", "waitForPageLoad"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ LoginPage }} from '{login_import}';
import {{ DashboardPage }} from '{dashboard_import}';
import {{ loginAs }} from '{auth_utils}';
import {{ waitForPageLoad }} from '{nav_utils}';

test.describe('Authentication - positive', () => {{
  test('should login with valid credentials', async ({{ page }}) => {{
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginAs(page, 'user@example.com', 'Password123!');
    await waitForPageLoad(page);
    const dashboard = new DashboardPage(page);
    await expect(dashboard.userGreeting).toBeVisible();
  }});

  test('should redirect to dashboard after login', async ({{ page }}) => {{
    const loginPage = new LoginPage(page);
    await loginPage.login('user@example.com', 'Password123!');
    await expect(page).toHaveURL(/.*dashboard/);
    const dashboard = new DashboardPage(page);
    await expect(dashboard.userGreeting).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Login with invalid credentials shows error",
        "feature_type": "auth",
        "test_type": "negative",
        "page_objects": ["LoginPage"],
        "utilities": [],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ LoginPage }} from '{login_import}';

test.describe('Authentication - negative', () => {{
  test('should show error on invalid password', async ({{ page }}) => {{
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.fillCredentials('user@example.com', 'wrongpassword');
    await loginPage.submit();
    await expect(loginPage.errorMessage).toBeVisible();
    await expect(loginPage.errorMessage).toContainText(/invalid|incorrect/i);
  }});

  test('should show error on empty email', async ({{ page }}) => {{
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.fillCredentials('', '');
    await loginPage.submit();
    await expect(loginPage.errorMessage).toBeVisible();
  }});

  test('should show rate limiting after multiple failures', async ({{ page }}) => {{
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    for (let i = 0; i < 5; i++) {{
      await loginPage.fillCredentials('user@example.com', 'wrong');
      await loginPage.submit();
    }}
    await expect(loginPage.errorMessage).toContainText(/try again later|locked/i);
  }});
}});""",
    },
    {
        "description": "Logout flow",
        "feature_type": "auth",
        "test_type": "positive",
        "page_objects": ["LoginPage", "DashboardPage"],
        "utilities": ["loginAs", "logout"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ LoginPage }} from '{login_import}';
import {{ DashboardPage }} from '{dashboard_import}';
import {{ loginAs, logout }} from '{auth_utils}';

test.describe('Authentication - logout', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should logout successfully', async ({{ page }}) => {{
    const dashboard = new DashboardPage(page);
    await dashboard.logout();
    const loginPage = new LoginPage(page);
    await expect(loginPage.emailInput).toBeVisible();
  }});

  test('should redirect to login after logout', async ({{ page }}) => {{
    await logout(page);
    await expect(page).toHaveURL(/.*login/);
  }});

  test('should not access dashboard after logout', async ({{ page }}) => {{
    await logout(page);
    await page.goto('/dashboard');
    const loginPage = new LoginPage(page);
    await expect(loginPage.emailInput).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Update profile name with utility",
        "feature_type": "form",
        "test_type": "positive",
        "page_objects": ["ProfilePage", "LoginPage"],
        "utilities": ["loginAs", "clearAndFill"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ ProfilePage }} from '{profile_import}';
import {{ LoginPage }} from '{login_import}';
import {{ loginAs }} from '{auth_utils}';
import {{ clearAndFill }} from '{form_utils}';

test.describe('Profile Management - positive', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should update profile name', async ({{ page }}) => {{
    const profile = new ProfilePage(page);
    await profile.goto();
    await clearAndFill(profile.nameInput, 'New Name');
    await profile.saveButton.click();
    await expect(profile.successMessage).toBeVisible();
  }});

  test('should cancel profile edit', async ({{ page }}) => {{
    const profile = new ProfilePage(page);
    await profile.goto();
    await clearAndFill(profile.nameInput, 'Changed Name');
    await profile.cancelButton.click();
    await expect(profile.successMessage).not.toBeVisible();
  }});
}});""",
    },
    {
        "description": "Update profile email with random data",
        "feature_type": "form",
        "test_type": "positive",
        "page_objects": ["ProfilePage", "LoginPage"],
        "utilities": ["loginAs", "generateRandomEmail"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ ProfilePage }} from '{profile_import}';
import {{ LoginPage }} from '{login_import}';
import {{ loginAs }} from '{auth_utils}';
import {{ generateRandomEmail }} from '{nav_utils}';

test.describe('Profile Management - email update', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should update email with random address', async ({{ page }}) => {{
    const profile = new ProfilePage(page);
    await profile.goto();
    const newEmail = generateRandomEmail();
    await profile.updateProfile('Test User', newEmail);
    await expect(profile.successMessage).toBeVisible();
  }});
}});""",
    },
    {
        "description": "User registration flow",
        "feature_type": "auth",
        "test_type": "positive",
        "page_objects": ["SignupPage", "LoginPage"],
        "utilities": ["generateRandomEmail", "generateRandomString"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ SignupPage }} from '{signup_import}';
import {{ LoginPage }} from '{login_import}';
import {{ generateRandomEmail }} from '{nav_utils}';
import {{ generateRandomString }} from '{data_utils}';

test.describe('Registration - positive', () => {{
  test('should register with valid data', async ({{ page }}) => {{
    const signup = new SignupPage(page);
    await signup.goto();
    const email = generateRandomEmail();
    const password = generateRandomString(12);
    await signup.fillForm('Test User', email, password);
    await signup.termsCheckbox.check();
    await signup.submit();
    await expect(signup.successMessage).toBeVisible();
  }});

  test('should redirect to login after registration', async ({{ page }}) => {{
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.fillForm('Test User', generateRandomEmail(), 'SecurePass1!');
    await signup.termsCheckbox.check();
    await signup.submit();
    await expect(page).toHaveURL(/.*login/);
    const loginPage = new LoginPage(page);
    await expect(loginPage.emailInput).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Registration with validation errors",
        "feature_type": "auth",
        "test_type": "negative",
        "page_objects": ["SignupPage"],
        "utilities": ["generateRandomEmail"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ SignupPage }} from '{signup_import}';

test.describe('Registration - negative', () => {{
  test('should show error on weak password', async ({{ page }}) => {{
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.fillForm('Test User', 'test@example.com', '123');
    await signup.termsCheckbox.check();
    await signup.submit();
    await expect(signup.page.getByText(/password|weak|strength/i)).toBeVisible();
  }});

  test('should show error when terms not accepted', async ({{ page }}) => {{
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.fillForm('Test User', 'test@example.com', 'SecurePass1!');
    await signup.submit();
    await expect(signup.page.getByText(/terms|agree|accept/i)).toBeVisible();
  }});

  test('should show error on mismatched passwords', async ({{ page }}) => {{
    const signup = new SignupPage(page);
    await signup.goto();
    await signup.nameInput.fill('Test User');
    await signup.emailInput.fill('test@example.com');
    await signup.passwordInput.fill('SecurePass1!');
    await signup.confirmInput.fill('DifferentPass1!');
    await signup.termsCheckbox.check();
    await signup.submit();
    await expect(signup.page.getByText(/match|confirm|mismatch/i)).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Search functionality",
        "feature_type": "search",
        "test_type": "positive",
        "page_objects": ["SearchResultsPage", "DashboardPage"],
        "utilities": ["loginAs", "waitForPageLoad"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ SearchResultsPage }} from '{search_import}';
import {{ DashboardPage }} from '{dashboard_import}';
import {{ loginAs, waitForPageLoad }} from '{auth_utils}';

test.describe('Search - positive', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should return results for valid query', async ({{ page }}) => {{
    const dashboard = new DashboardPage(page);
    await dashboard.search('playwright');
    const results = new SearchResultsPage(page);
    await expect(results.resultsList).toBeVisible();
    await expect(results.resultItems.first()).toBeVisible();
  }});

  test('should filter results by category', async ({{ page }}) => {{
    const dashboard = new DashboardPage(page);
    await dashboard.search('test');
    const results = new SearchResultsPage(page);
    await results.applyFilter('documentation');
    await expect(results.resultsList).toBeVisible();
  }});

  test('should show no results for nonsense query', async ({{ page }}) => {{
    const dashboard = new DashboardPage(page);
    await dashboard.search('zzzxxxxynonsense');
    const results = new SearchResultsPage(page);
    await expect(results.noResultsMessage).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Payment flow",
        "feature_type": "payment",
        "test_type": "positive",
        "page_objects": ["PaymentPage", "LoginPage"],
        "utilities": ["loginAs", "waitForPageLoad"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ PaymentPage }} from '{payment_import}';
import {{ LoginPage }} from '{login_import}';
import {{ loginAs, waitForPageLoad }} from '{auth_utils}';

test.describe('Payment - positive', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should complete payment with valid card', async ({{ page }}) => {{
    const payment = new PaymentPage(page);
    await payment.goto();
    await payment.fillCardDetails('4111111111111111', '12/28', '123', 'Test User');
    await payment.pay();
    await expect(payment.successMessage).toBeVisible();
  }});

  test('should process payment and show confirmation', async ({{ page }}) => {{
    const payment = new PaymentPage(page);
    await payment.goto();
    await payment.fillCardDetails('4242424242424242', '01/29', '456', 'Test User');
    await payment.pay();
    await expect(payment.successMessage).toBeVisible();
    await expect(payment.successMessage).toContainText(/confirmed|successful/i);
  }});
}});""",
    },
    {
        "description": "Payment error handling",
        "feature_type": "payment",
        "test_type": "negative",
        "page_objects": ["PaymentPage", "LoginPage"],
        "utilities": ["loginAs"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ PaymentPage }} from '{payment_import}';
import {{ LoginPage }} from '{login_import}';
import {{ loginAs }} from '{auth_utils}';

test.describe('Payment - error handling', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should reject expired card', async ({{ page }}) => {{
    const payment = new PaymentPage(page);
    await payment.goto();
    await payment.fillCardDetails('4111111111111111', '01/20', '123', 'Test User');
    await payment.pay();
    await expect(payment.errorMessage).toBeVisible();
  }});

  test('should reject invalid CVV', async ({{ page }}) => {{
    const payment = new PaymentPage(page);
    await payment.goto();
    await payment.fillCardDetails('4111111111111111', '12/28', '12', 'Test User');
    await payment.pay();
    await expect(payment.errorMessage).toBeVisible();
  }});

  test('should reject declined card', async ({{ page }}) => {{
    const payment = new PaymentPage(page);
    await payment.goto();
    await payment.fillCardDetails('4000000000000002', '12/28', '123', 'Test User');
    await payment.pay();
    await expect(payment.errorMessage).toContainText(/declined|insufficient/i);
  }});
}});""",
    },
    {
        "description": "Admin user management - create user",
        "feature_type": "crud",
        "test_type": "positive",
        "page_objects": ["AdminUserListPage", "LoginPage"],
        "utilities": ["loginAs", "generateRandomEmail"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ AdminUserListPage }} from '{admin_import}';
import {{ LoginPage }} from '{login_import}';
import {{ loginAs }} from '{auth_utils}';
import {{ generateRandomEmail }} from '{nav_utils}';

test.describe('Admin - User Management', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'admin@example.com', 'Admin123!');
  }});

  test('should add new user', async ({{ page }}) => {{
    const admin = new AdminUserListPage(page);
    await admin.goto();
    await admin.addUserButton.click();
    const email = generateRandomEmail();
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Name').fill('New User');
    await page.getByRole('button', {{ name: /save/i }}).click();
    await expect(admin.successMessage).toBeVisible();
    await admin.searchUser(email);
    await expect(admin.userTable).toContainText(email);
  }});

  test('should delete existing user', async ({{ page }}) => {{
    const admin = new AdminUserListPage(page);
    await admin.goto();
    await admin.deleteUser('olduser@example.com');
    await admin.confirmDelete.click();
    await expect(admin.successMessage).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Settings - update preferences",
        "feature_type": "form",
        "test_type": "positive",
        "page_objects": ["SettingsPage", "LoginPage"],
        "utilities": ["loginAs", "clearAndFill"],
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ SettingsPage }} from '{settings_import}';
import {{ LoginPage }} from '{login_import}';
import {{ loginAs }} from '{auth_utils}';
import {{ clearAndFill }} from '{form_utils}';

test.describe('Settings - preferences', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should update theme preference', async ({{ page }}) => {{
    const settings = new SettingsPage(page);
    await settings.goto();
    await settings.themeSelect.selectOption('dark');
    await settings.saveButton.click();
    await expect(settings.successMessage).toBeVisible();
  }});

  test('should toggle notifications', async ({{ page }}) => {{
    const settings = new SettingsPage(page);
    await settings.goto();
    await settings.notificationsToggle.click();
    await settings.saveButton.click();
    await expect(settings.successMessage).toBeVisible();
  }});

  test('should update language', async ({{ page }}) => {{
    const settings = new SettingsPage(page);
    await settings.goto();
    await settings.languageSelect.selectOption('es');
    await settings.saveButton.click();
    await expect(settings.successMessage).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Raw Playwright for unsupported element",
        "feature_type": "form",
        "test_type": "negative",
        "page_objects": [],
        "utilities": [],
        "choose_between_utility_and_raw": True,
        "code_template": """import {{ test, expect }} from '@playwright/test';

test.describe('File upload boundary', () => {{
  test('should reject file over size limit', async ({{ page }}) => {{
    await page.goto('/upload');
    const fileChooser = page.waitForEvent('filechooser');
    await page.getByRole('button', {{ name: /upload/i }}).click();
    await fileChooser.then(fc => fc.setFiles('tests/fixtures/large-file.pdf'));
    await expect(page.getByTestId('upload-error')).toContainText(/too large|exceeds/i);
  }});

  test('should reject invalid file type', async ({{ page }}) => {{
    await page.goto('/upload');
    const fileChooser = page.waitForEvent('filechooser');
    await page.getByRole('button', {{ name: /upload/i }}).click();
    await fileChooser.then(fc => fc.setFiles('tests/fixtures/file.exe'));
    await expect(page.getByTestId('upload-error')).toContainText(/type|format|invalid/i);
  }});
}});""",
    },
    {
        "description": "Choose existing utility vs raw Playwright for auth",
        "feature_type": "auth",
        "test_type": "edge",
        "page_objects": ["LoginPage", "DashboardPage"],
        "utilities": ["loginAs", "waitForPageLoad"],
        "choose_between_utility_and_raw": True,
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ LoginPage }} from '{login_import}';
import {{ DashboardPage }} from '{dashboard_import}';
import {{ loginAs }} from '{auth_utils}';

test.describe('Authentication - edge cases', () => {{
  test('should handle concurrent login from two tabs', async ({{ page, context }}) => {{
    const page2 = await context.newPage();
    await loginAs(page, 'user@example.com', 'Password123!');
    await loginAs(page2, 'user@example.com', 'Password123!');
    const dashboard1 = new DashboardPage(page);
    const dashboard2 = new DashboardPage(page2);
    await expect(dashboard1.userGreeting).toBeVisible();
    await expect(dashboard2.userGreeting).toBeVisible();
  }});

  test('should handle login with special characters in password', async ({{ page }}) => {{
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.fillCredentials('user@example.com', 'P@ssw0rd!$#&*()');
    await loginPage.submit();
    const dashboard = new DashboardPage(page);
    await expect(dashboard.userGreeting).toBeVisible();
  }});
}});""",
    },
    {
        "description": "Mixed: use utility where available, raw Playwright for the rest",
        "feature_type": "navigation",
        "test_type": "positive",
        "page_objects": ["DashboardPage", "ProfilePage", "LoginPage"],
        "utilities": ["loginAs"],
        "choose_between_utility_and_raw": True,
        "code_template": """import {{ test, expect }} from '@playwright/test';
import {{ LoginPage }} from '{login_import}';
import {{ DashboardPage }} from '{dashboard_import}';
import {{ ProfilePage }} from '{profile_import}';
import {{ loginAs }} from '{auth_utils}';

test.describe('Navigation - user flow', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await loginAs(page, 'user@example.com', 'Password123!');
  }});

  test('should navigate from dashboard to profile and back', async ({{ page }}) => {{
    const dashboard = new DashboardPage(page);
    await dashboard.profileLink.click();
    await expect(page).toHaveURL(/.*profile/);
    const profile = new ProfilePage(page);
    await expect(profile.nameInput).toBeVisible();
    await page.goBack();
    await expect(dashboard.userGreeting).toBeVisible();
  }});

  test('should show notifications badge', async ({{ page }}) => {{
    const dashboard = new DashboardPage(page);
    await expect(dashboard.notificationsBadge).toBeVisible();
    const count = await dashboard.notificationsBadge.textContent();
    expect(Number(count)).toBeGreaterThanOrEqual(0);
  }});
}});""",
    },
]


def format_import_path(template: str, page_key: str, import_path: str) -> str:
    return template.replace("{" + page_key + "}", import_path)


def generate_example(scenario: dict, po_map: dict, util_map: dict) -> dict:
    description = scenario["description"]
    feature_type = scenario["feature_type"]
    test_type = scenario["test_type"]
    code_template = scenario["code_template"]

    po_names = scenario["page_objects"]
    util_names = scenario["utilities"]

    selected_pos = [po_map[name] for name in po_names]
    selected_utils = [util_map[name] for name in util_names]

    po_blocks = []
    for po in selected_pos:
        po_blocks.append(f"class {po.class_name}:")
        for name, sel in po.selectors.items():
            po_blocks.append(f"  {name}: {sel}")
        for m in po.methods:
            po_blocks.append(f"  {m}")
    po_text = "\n".join(po_blocks)

    util_text = ""
    if selected_utils:
        util_lines = []
        for u in selected_utils:
            util_lines.append(f"{u.signature}  // {u.description}")
        util_text = "\n".join(util_lines)

    context_parts = [f"Feature: {description}"]
    context_parts.append("")
    if selected_pos:
        context_parts.append("Existing page objects:")
        context_parts.append(po_text)
        context_parts.append("")
    if selected_utils:
        context_parts.append("Available utilities:")
        context_parts.append(util_text)
        context_parts.append("")
    if scenario.get("choose_between_utility_and_raw", False):
        context_parts.append(
            "Note: Use existing utilities where appropriate. "
            "Fall back to raw Playwright for cases the utilities don't cover."
        )
    else:
        context_parts.append(
            "Use existing page objects and utilities. "
            "Import from the correct paths."
        )

    user_content = "\n".join(context_parts)

    import_map = {
        "{login_import}": "../pages/LoginPage",
        "{dashboard_import}": "../pages/DashboardPage",
        "{profile_import}": "../pages/ProfilePage",
        "{signup_import}": "../pages/SignupPage",
        "{search_import}": "../pages/SearchResultsPage",
        "{settings_import}": "../pages/SettingsPage",
        "{payment_import}": "../pages/PaymentPage",
        "{admin_import}": "../pages/AdminUserListPage",
        "{auth_utils}": "../utils/auth",
        "{nav_utils}": "../utils/navigation",
        "{form_utils}": "../utils/forms",
        "{data_utils}": "../utils/data",
        "{upload_utils}": "../utils/upload",
        "{debug_utils}": "../utils/debug",
        "{dialog_utils}": "../utils/dialogs",
    }

    code = code_template
    for placeholder, path in import_map.items():
        code = code.replace(placeholder, path)

    code = code.replace("{{", "{").replace("}}", "}")

    return {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": code},
        ],
        "metadata": {
            "feature_type": feature_type,
            "test_type": test_type,
            "description": description,
            "uses_utilities": bool(selected_utils),
            "uses_page_objects": bool(selected_pos),
            "choose_between_utility_and_raw": scenario.get("choose_between_utility_and_raw", False),
            "source": "synthetic",
        },
    }


def generate_positive_and_negative_variants(example: dict) -> list[dict]:
    """Swap test type and add a negative variant for the same feature."""
    meta = example["metadata"].copy()
    if meta["test_type"] == "negative":
        return [example]

    user_msg = example["messages"][0]["content"]
    assistant_msg = example["messages"][1]["content"]

    neg_variant = user_msg.replace(
        f"Feature: {meta['description']}",
        f"Feature: {meta['description']} (error cases)",
    )

    return [
        example,
        {
            "messages": [
                {"role": "user", "content": neg_variant},
                {"role": "assistant", "content": assistant_msg.replace(
                    "'positive'", "'negative'"
                ).replace(
                    "'should'", "'should handle errors when'"
                )},
            ],
            "metadata": {
                **meta,
                "test_type": "negative",
                "description": f"{meta['description']} (error cases)",
            },
        },
    ]


def generate_raw_playwright_variant(example: dict) -> dict:
    """Generate a variant that explicitly avoids utilities and uses raw Playwright."""
    meta = example["metadata"].copy()
    user_msg = example["messages"][0]["content"]
    assistant_msg = example["messages"][1]["content"]

    raw_user = user_msg.replace(
        "Use existing page objects and utilities.",
        "Do NOT use any existing page objects or utilities. Write the test using raw Playwright locators only.",
    )

    import_lines = [l for l in assistant_msg.split("\n") if l.startswith("import")]
    has_page_imports = any("Page" in l for l in import_lines)
    has_util_imports = any("utils" in l for l in import_lines)

    if has_page_imports or has_util_imports:
        raw_code_lines = [
            "import { test, expect } from '@playwright/test';",
        ]
        in_code = False
        for line in assistant_msg.split("\n"):
            if line.startswith("test(") or line.startswith("test.") or line.startswith("test.describe"):
                in_code = True
            if in_code:
                raw_code_lines.append(line)

        raw_code = "\n".join(raw_code_lines)

        return {
            "messages": [
                {"role": "user", "content": raw_user},
                {"role": "assistant", "content": raw_code},
            ],
            "metadata": {
                **meta,
                "description": f"{meta['description']} (raw Playwright)",
                "uses_utilities": False,
                "uses_page_objects": False,
            },
        }
    return None


def main():
    random.seed(42)
    examples = []

    for scenario in SCENARIO_TEMPLATES:
        example = generate_example(scenario, PAGE_OBJECTS, UTILITIES)
        examples.append(example)

    expanded = []
    for ex in examples:
        expanded.append(ex)
        raw_variant = generate_raw_playwright_variant(ex)
        if raw_variant:
            expanded.append(raw_variant)
        variants = generate_positive_and_negative_variants(ex)
        for v in variants:
            if v != ex and v not in expanded:
                expanded.append(v)

    import_path = "/Users/skaparwan/Documents/sdet-training-data"
    import os
    os.makedirs(import_path, exist_ok=True)

    output_file = f"{import_path}/sdet-training-data.jsonl"
    with open(output_file, "w") as f:
        for ex in expanded:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    total = len(expanded)
    with_utils = sum(1 for e in expanded if e["metadata"].get("uses_utilities"))
    with_po = sum(1 for e in expanded if e["metadata"].get("uses_page_objects"))
    choose = sum(1 for e in expanded if e["metadata"].get("choose_between_utility_and_raw"))
    neg = sum(1 for e in expanded if e["metadata"].get("test_type") == "negative")
    pos = sum(1 for e in expanded if e["metadata"].get("test_type") == "positive")

    print(f"Generated {total} training examples")
    print(f"  Positive: {pos}, Negative: {neg}")
    print(f"  With page objects: {with_po}")
    print(f"  With utilities: {with_utils}")
    print(f"  Choose-between variants: {choose}")
    print(f"  Raw Playwright variants: {total - with_po}")
    print(f"Output: {output_file}")
    print("\n--- Example 1 (first entry) ---")
    first = expanded[0]
    print(json.dumps(first, indent=2, ensure_ascii=False)[:1500])

    # also write a huggingface-compatible dataset
    hf_output = f"{import_path}/sdet-training-data-hf.jsonl"
    with open(hf_output, "w") as f:
        for ex in expanded:
            hf_entry = {
                "instruction": ex["messages"][0]["content"].split("\n\n")[0]
                    if "\n\n" in ex["messages"][0]["content"]
                    else ex["messages"][0]["content"][:100],
                "input": ex["messages"][0]["content"],
                "output": ex["messages"][1]["content"],
            }
            f.write(json.dumps(hf_entry, ensure_ascii=False) + "\n")
    print(f"\nHF-format output: {hf_output}")
    print(f"  {total} entries")


if __name__ == "__main__":
    main()
