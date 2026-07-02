#!/usr/bin/env python3
"""Generate 2000+ SDET training examples in canonical Unsloth ShareGPT format.

Multiplies example count by permuting:
  - page object combinations (which POs are "available" in the repo)
  - utility combinations (which utils are "available")
  - test data variants (different credentials, queries, card numbers, etc.)
  - description/semantic variants
  - with/without utilities
  - single-turn vs multi-turn dialogue
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

random.seed(42)

PAGE_OBJECT_SOURCES: Dict[str, str] = {
    "LoginPage": """import { Page, Locator } from '@playwright/test';
export class LoginPage {
  readonly page: Page;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly loginButton: Locator;
  readonly errorMessage: Locator;
  readonly rememberMe: Locator;
  readonly forgotPassword: Locator;
  constructor(page: Page) {
    this.page = page; this.emailInput = page.getByLabel('Email address');
    this.passwordInput = page.getByLabel('Password');
    this.loginButton = page.getByRole('button', { name: /sign in/i });
    this.errorMessage = page.getByTestId('login-error');
    this.rememberMe = page.getByRole('checkbox', { name: /remember/i });
    this.forgotPassword = page.getByRole('link', { name: /forgot/i });
  }
  async goto() { await this.page.goto('/login'); }
  async fillCredentials(email: string, password: string) { await this.emailInput.fill(email); await this.passwordInput.fill(password); }
  async submit() { await this.loginButton.click(); }
  async login(email: string, password: string) { await this.goto(); await this.fillCredentials(email, password); await this.submit(); }
}""",
    "DashboardPage": """import { Page, Locator } from '@playwright/test';
export class DashboardPage {
  readonly page: Page;
  readonly userGreeting: Locator;
  readonly logoutButton: Locator;
  readonly navSidebar: Locator;
  readonly profileLink: Locator;
  readonly searchInput: Locator;
  readonly notificationsBadge: Locator;
  constructor(page: Page) {
    this.page = page;
    this.userGreeting = page.getByTestId('user-greeting');
    this.logoutButton = page.getByRole('button', { name: /log out/i });
    this.navSidebar = page.locator('nav.sidebar');
    this.profileLink = page.getByRole('link', { name: /profile/i });
    this.searchInput = page.getByPlaceholder('Search...');
    this.notificationsBadge = page.getByTestId('notification-count');
  }
  async logout() { await this.logoutButton.click(); }
  async search(query: string) { await this.searchInput.fill(query); await this.searchInput.press('Enter'); }
}""",
    "ProfilePage": """import { Page, Locator } from '@playwright/test';
export class ProfilePage {
  readonly page: Page; readonly nameInput: Locator; readonly emailInput: Locator;
  readonly saveButton: Locator; readonly avatarUpload: Locator;
  readonly cancelButton: Locator; readonly successMessage: Locator;
  constructor(page: Page) {
    this.page = page; this.nameInput = page.getByLabel('Full name');
    this.emailInput = page.getByLabel('Email address');
    this.saveButton = page.getByRole('button', { name: /save/i });
    this.avatarUpload = page.locator('input[type="file"]');
    this.cancelButton = page.getByRole('link', { name: /cancel/i });
    this.successMessage = page.getByTestId('save-success');
  }
  async goto() { await this.page.goto('/profile'); }
  async updateProfile(name: string, email: string) { await this.nameInput.fill(name); await this.emailInput.fill(email); await this.saveButton.click(); }
}""",
    "SignupPage": """import { Page, Locator } from '@playwright/test';
export class SignupPage {
  readonly page: Page; readonly nameInput: Locator; readonly emailInput: Locator;
  readonly passwordInput: Locator; readonly confirmInput: Locator;
  readonly submitButton: Locator; readonly termsCheckbox: Locator; readonly successMessage: Locator;
  constructor(page: Page) {
    this.page = page; this.nameInput = page.getByLabel('Full name');
    this.emailInput = page.getByLabel('Email');
    this.passwordInput = page.getByLabel('Create password');
    this.confirmInput = page.getByLabel('Confirm password');
    this.submitButton = page.getByRole('button', { name: /create account/i });
    this.termsCheckbox = page.getByRole('checkbox', { name: /terms/i });
    this.successMessage = page.getByTestId('signup-success');
  }
  async goto() { await this.page.goto('/signup'); }
  async fillForm(name: string, email: string, password: string) { await this.nameInput.fill(name); await this.emailInput.fill(email); await this.passwordInput.fill(password); await this.confirmInput.fill(password); }
  async submit() { await this.submitButton.click(); }
}""",
    "SearchResultsPage": """import { Page, Locator } from '@playwright/test';
export class SearchResultsPage {
  readonly page: Page; readonly resultsList: Locator; readonly resultItems: Locator;
  readonly noResultsMessage: Locator; readonly filterDropdown: Locator;
  readonly sortSelect: Locator; readonly pagination: Locator;
  constructor(page: Page) {
    this.page = page; this.resultsList = page.getByTestId('search-results');
    this.resultItems = page.locator('[data-testid="result-item"]');
    this.noResultsMessage = page.getByTestId('no-results');
    this.filterDropdown = page.getByLabel('Filter by');
    this.sortSelect = page.getByLabel('Sort by');
    this.pagination = page.locator('nav.pagination');
  }
  async goto(query?: string) { await this.page.goto(query ? `/search?q=${query}` : '/search'); }
  async applyFilter(filter: string) { await this.filterDropdown.selectOption(filter); }
  async sortBy(option: string) { await this.sortSelect.selectOption(option); }
}""",
    "SettingsPage": """import { Page, Locator } from '@playwright/test';
export class SettingsPage {
  readonly page: Page; readonly themeSelect: Locator; readonly languageSelect: Locator;
  readonly notificationsToggle: Locator; readonly saveButton: Locator; readonly successMessage: Locator;
  constructor(page: Page) {
    this.page = page; this.themeSelect = page.getByLabel('Theme');
    this.languageSelect = page.getByLabel('Language');
    this.notificationsToggle = page.getByRole('switch', { name: /notifications/i });
    this.saveButton = page.getByRole('button', { name: /save settings/i });
    this.successMessage = page.getByTestId('settings-saved');
  }
  async goto() { await this.page.goto('/settings'); }
  async updateSetting(label: string, value: string) { await this.page.getByLabel(label).fill(value); await this.saveButton.click(); }
}""",
    "PaymentPage": """import { Page, Locator } from '@playwright/test';
export class PaymentPage {
  readonly page: Page; readonly cardInput: Locator; readonly expiryInput: Locator;
  readonly cvvInput: Locator; readonly nameOnCard: Locator; readonly payButton: Locator;
  readonly errorMessage: Locator; readonly successMessage: Locator;
  constructor(page: Page) {
    this.page = page; this.cardInput = page.getByPlaceholder('Card number');
    this.expiryInput = page.getByPlaceholder('MM/YY'); this.cvvInput = page.getByPlaceholder('CVV');
    this.nameOnCard = page.getByLabel('Name on card');
    this.payButton = page.getByRole('button', { name: /pay/i });
    this.errorMessage = page.getByTestId('payment-error');
    this.successMessage = page.getByTestId('payment-success');
  }
  async goto() { await this.page.goto('/payment'); }
  async fillCardDetails(card: string, expiry: string, cvv: string, name: string) { await this.cardInput.fill(card); await this.expiryInput.fill(expiry); await this.cvvInput.fill(cvv); await this.nameOnCard.fill(name); }
  async pay() { await this.payButton.click(); }
}""",
    "AdminUserListPage": """import { Page, Locator } from '@playwright/test';
export class AdminUserListPage {
  readonly page: Page; readonly userTable: Locator; readonly searchInput: Locator;
  readonly addUserButton: Locator; readonly deleteButton: Locator;
  readonly confirmDelete: Locator; readonly successMessage: Locator;
  constructor(page: Page) {
    this.page = page; this.userTable = page.locator('table.users');
    this.searchInput = page.getByPlaceholder('Search users...');
    this.addUserButton = page.getByRole('button', { name: /add user/i });
    this.deleteButton = page.getByRole('button', { name: /delete/i });
    this.confirmDelete = page.getByRole('button', { name: /confirm/i });
    this.successMessage = page.getByTestId('action-success');
  }
  async goto() { await this.page.goto('/admin/users'); }
  async searchUser(query: string) { await this.searchInput.fill(query); await this.searchInput.press('Enter'); }
  async deleteUser(email: string) { await this.searchUser(email); await this.deleteButton.click(); }
}""",
}

UTILITY_SOURCES: Dict[str, str] = {
    "loginAs": """import { Page } from '@playwright/test';
export async function loginAs(page: Page, email: string, password: string) {
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(/\\/dashboard/);
}""",
    "logout": """import { Page } from '@playwright/test';
export async function logout(page: Page) {
  await page.getByRole('button', { name: /log out/i }).click();
  await page.waitForURL(/\\/login/);
}""",
    "waitForPageLoad": """import { Page } from '@playwright/test';
export async function waitForPageLoad(page: Page) {
  await page.waitForLoadState('networkidle');
}""",
    "generateRandomEmail": """export function generateRandomEmail(): string {
  const id = Math.random().toString(36).substring(2, 10);
  return `test-${id}@example.com`;
}""",
    "generateRandomString": """export function generateRandomString(length: number): string {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) { result += chars.charAt(Math.floor(Math.random() * chars.length)); }
  return result;
}""",
    "clearAndFill": """import { Locator } from '@playwright/test';
export async function clearAndFill(locator: Locator, value: string) {
  await locator.clear();
  await locator.fill(value);
}""",
    "uploadFile": """import { Page } from '@playwright/test';
export async function uploadFile(page: Page, selector: string, filePath: string) {
  const fileChooser = page.waitForEvent('filechooser');
  await page.locator(selector).click();
  await fileChooser.then(fc => fc.setFiles(filePath));
}""",
    "dismissDialog": """import { Page } from '@playwright/test';
export async function dismissDialog(page: Page, accept: boolean) {
  page.on('dialog', dialog => {
    if (accept) dialog.accept();
    else dialog.dismiss();
  });
}""",
}

PO_IMPORTS: Dict[str, str] = {
    "LoginPage": "../pages/LoginPage",
    "DashboardPage": "../pages/DashboardPage",
    "ProfilePage": "../pages/ProfilePage",
    "SignupPage": "../pages/SignupPage",
    "SearchResultsPage": "../pages/SearchResultsPage",
    "SettingsPage": "../pages/SettingsPage",
    "PaymentPage": "../pages/PaymentPage",
    "AdminUserListPage": "../pages/AdminUserListPage",
}
UTIL_IMPORTS: Dict[str, str] = {
    "loginAs": "../utils/auth", "logout": "../utils/auth",
    "waitForPageLoad": "../utils/navigation", "generateRandomEmail": "../utils/navigation",
    "generateRandomString": "../utils/data", "clearAndFill": "../utils/forms",
    "uploadFile": "../utils/upload", "dismissDialog": "../utils/dialogs",
}

SYSTEM_PROMPT = "You are an expert Senior SDET. Given automation repo context and a test scenario, output only the Playwright test code. Be concise. No reasoning, no explanation."


def build_context_block(pos: List[str], utils: List[str]) -> str:
    parts = ["=== Repo Context ===", "Base URL: http://localhost:3000\n"]
    if pos:
        parts.append("=== Page Objects ===")
        for name in pos:
            parts.append(f"File: pages/{name}.ts")
            parts.append("```typescript")
            parts.append(PAGE_OBJECT_SOURCES[name])
            parts.append("```\n")
    if utils:
        parts.append("=== Utilities ===")
        seen: Dict[str, List[str]] = {}
        for name in utils:
            seen.setdefault(UTIL_IMPORTS[name], []).append(name)
        for imp, names in seen.items():
            fname = imp.split("/")[-1] + ".ts"
            parts.append(f"File: utils/{fname}")
            parts.append("```typescript")
            parts.append("\n\n".join(UTILITY_SOURCES[n] for n in names))
            parts.append("```\n")
    return "\n".join(parts)


def build_user_message(pos: List[str], utils: List[str], task: str, use_utils: bool) -> str:
    inst = (
        "Use existing page objects and utilities where appropriate. Import from the correct paths. "
        "Fall back to raw Playwright for cases the utilities don't cover."
        if use_utils
        else "Write the test using raw Playwright locators only. Do NOT use any existing page objects or utilities."
    )
    return f"{SYSTEM_PROMPT}\n\n{build_context_block(pos, utils)}\n\n=== Task ===\n{task}\n{inst}"


def imports(pos: List[str], utils: List[str], use_utils: bool) -> str:
    if not use_utils:
        return "import { test, expect } from '@playwright/test';"
    lines = ["import { test, expect } from '@playwright/test';"]
    for p in pos:
        lines.append(f"import {{ {p} }} from '{PO_IMPORTS[p]}';")
    seen: Dict[str, List[str]] = {}
    for u in utils:
        seen.setdefault(UTIL_IMPORTS[u], []).append(u)
    for imp, names in sorted(seen.items()):
        lines.append(f"import {{ {', '.join(sorted(names))} }} from '{imp}';")
    return "\n".join(lines)


def pv(po: str) -> str:
    return po[0].lower() + po[1:]


# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------
LOGIN_CREDS = [
    ("user@example.com", "Password123!"), ("admin@example.com", "Admin123!"),
    ("test@test.com", "TestPass1!"), ("dev@company.co", "DevPass!23"),
    ("ops@internal.net", "0ps!Secure"), ("qa@test.io", "QaTeam!2024"),
]
EMAILS = ["newuser@example.com", "test.user@domain.com", "hello@world.co",
          "contact@startup.io", "dev@company.com", "ops@internal.net"]
NAMES = ["Test User", "John Doe", "Alice Smith", "Bob Johnson", "Carol Williams"]
QUERIES = ["playwright", "testing", "automation", "dashboard", "profile",
           "settings", "users", "reports", "analytics", "documents"]
FILTERS = ["documentation", "guides", "api", "tutorials", "reference"]
CARDS = [("4111111111111111", "12/28", "123"), ("4242424242424242", "01/29", "456"),
         ("5555555555554444", "11/27", "789"), ("4000056655665556", "10/30", "321")]
EXPIRED_CARDS = [("4111111111111111", "01/20", "123"), ("4242424242424242", "02/21", "456")]
THEMES = ["dark", "light", "system"]
LANGS = ["es", "fr", "de", "ja", "pt"]
ADMIN_CREDS = [("admin@example.com", "Admin123!"), ("superadmin@co.com", "Super!Admin")]


# ---------------------------------------------------------------------------
# Families: each family has name, PO combos, util combos, and a code generator
# ---------------------------------------------------------------------------

@dataclass
class Family:
    name: str
    feature_type: str
    po_combos: List[List[str]]
    util_combos: List[List[str]]
    code_gen: Callable[[List[str], List[str], bool, int], Tuple[str, str, str]]  # -> (code, ttype, task_desc)


# --- Login family ---
def gen_login(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    cred = LOGIN_CREDS[variant % len(LOGIN_CREDS)]
    sub = variant // len(LOGIN_CREDS)
    patterns = [
        ("valid", f"Write a test for logging in with {cred[0]} and verifying the dashboard"),
        ("positive", f"Write a test for successful login and user greeting visibility"),
        ("valid", f"Write a test for authentication with valid credentials"),
    ]
    label, desc = patterns[sub % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Login", () => {', ""]
    if use_utils and "loginAs" in utils:
        lines.append(f'  test("should login with {cred[0]}", async ({{ page }}) => {{')
        lines.append(f"    await loginAs(page, '{cred[0]}', '{cred[1]}');")
        if use_utils and "waitForPageLoad" in utils:
            lines.append("    await waitForPageLoad(page);")
        if "DashboardPage" in pos:
            d = pv("DashboardPage")
            lines.append(f"    const {d} = new DashboardPage(page);")
            lines.append(f"    await expect({d}.userGreeting).toBeVisible();")
        else:
            lines.append("    await expect(page).toHaveURL(/.*dashboard/);")
    else:
        lines.append(f'  test("should login with {cred[0]}", async ({{ page }}) => {{')
        if "LoginPage" in pos:
            l = pv("LoginPage")
            lines.append(f"    const {l} = new LoginPage(page);")
            lines.append(f"    await {l}.goto();")
            lines.append(f"    await {l}.fillCredentials('{cred[0]}', '{cred[1]}');")
            lines.append(f"    await {l}.submit();")
        else:
            lines.append("    await page.goto('/login');")
            lines.append(f"    await page.getByLabel('Email address').fill('{cred[0]}');")
            lines.append(f"    await page.getByLabel('Password').fill('{cred[1]}');")
            lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
        if "DashboardPage" in pos:
            d = pv("DashboardPage")
            lines.append(f"    const {d} = new DashboardPage(page);")
            lines.append(f"    await expect({d}.userGreeting).toBeVisible();")
        else:
            lines.append("    await expect(page).toHaveURL(/.*dashboard/);")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)

def gen_login_error(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    cred = LOGIN_CREDS[variant % len(LOGIN_CREDS)]
    patterns = [
        ("negative", f"Write a test showing error when password is wrong for {cred[0]}"),
        ("negative", f"Write a test for invalid login credentials showing error message"),
    ]
    label, desc = patterns[variant % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Login Errors", () => {', ""]
    lines.append(f'  test("should show error on invalid password", async ({{ page }}) => {{')
    if "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append(f"    await {l}.goto();")
        lines.append(f"    await {l}.fillCredentials('{cred[0]}', 'wrongpassword');")
        lines.append(f"    await {l}.submit();")
        lines.append(f"    await expect({l}.errorMessage).toBeVisible();")
    else:
        lines.append("    await page.goto('/login');")
        lines.append(f"    await page.getByLabel('Email address').fill('{cred[0]}');")
        lines.append("    await page.getByLabel('Password').fill('wrongpassword');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
        lines.append("    await expect(page.getByTestId('login-error')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Logout family ---
def gen_logout(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    cred = LOGIN_CREDS[variant % len(LOGIN_CREDS)]
    patterns = [
        ("positive", f"Write a test for logging out as {cred[0]}"),
        ("positive", f"Write a test verifying logout redirects to login page"),
    ]
    label, desc = patterns[variant % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Logout", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append(f"    await loginAs(page, '{cred[0]}', '{cred[1]}');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append(f"    await {l}.login('{cred[0]}', '{cred[1]}');")
    else:
        lines.append("    await page.goto('/login');")
        lines.append(f"    await page.getByLabel('Email address').fill('{cred[0]}');")
        lines.append(f"    await page.getByLabel('Password').fill('{cred[1]}');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("should logout successfully", async ({{ page }}) => {{')
    if use_utils and "logout" in utils:
        lines.append("    await logout(page);")
        lines.append("    await expect(page).toHaveURL(/.*login/);")
    elif "DashboardPage" in pos:
        d = pv("DashboardPage")
        lines.append(f"    const {d} = new DashboardPage(page);")
        lines.append(f"    await {d}.logout();")
        lines.append("    await expect(page).toHaveURL(/.*login/);")
    else:
        lines.append("    await page.getByRole('button', { name: /log out/i }).click();")
        lines.append("    await expect(page).toHaveURL(/.*login/);")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Profile family ---
def gen_profile(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    cred = LOGIN_CREDS[variant % len(LOGIN_CREDS)]
    name = NAMES[variant % len(NAMES)]
    email = EMAILS[variant % len(EMAILS)]
    sub = variant // len(LOGIN_CREDS)
    patterns = [
        ("positive", f"Write a test for updating profile name to '{name}'"),
        ("positive", f"Write a test for updating profile email to a new address"),
        ("positive", f"Write a test for cancelling profile edit without saving"),
    ]
    label, desc = patterns[sub % len(patterns)]
    has_clear = use_utils and "clearAndFill" in utils
    has_email_util = use_utils and "generateRandomEmail" in utils
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Profile", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append(f"    await loginAs(page, '{cred[0]}', '{cred[1]}');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append(f"    await {l}.login('{cred[0]}', '{cred[1]}');")
    else:
        lines.append("    await page.getByLabel('Email address').fill('user@example.com');")
        lines.append("    await page.getByLabel('Password').fill('Password123!');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("should update profile data", async ({{ page }}) => {{')
    if "ProfilePage" in pos:
        pp = pv("ProfilePage")
        lines.append(f"    const {pp} = new ProfilePage(page);")
        lines.append(f"    await {pp}.goto();")
        if "email" in desc:
            if has_email_util:
                lines.append("    const newEmail = generateRandomEmail();")
            else:
                lines.append(f"    const newEmail = '{email}';")
            lines.append(f"    await {pp}.updateProfile('{name}', newEmail);")
        elif "cancel" in desc:
            if has_clear:
                lines.append(f"    await clearAndFill({pp}.nameInput, '{name}');")
            else:
                lines.append(f"    await {pp}.nameInput.fill('{name}');")
            lines.append(f"    await {pp}.cancelButton.click();")
            lines.append(f"    await expect({pp}.successMessage).not.toBeVisible();")
            lines.append("  });\n  });\n});")
            return ("\n".join(lines), label, desc)
        else:
            if has_clear:
                lines.append(f"    await clearAndFill({pp}.nameInput, '{name}');")
            else:
                lines.append(f"    await {pp}.nameInput.fill('{name}');")
            lines.append(f"    await {pp}.saveButton.click();")
        lines.append(f"    await expect({pp}.successMessage).toBeVisible();")
    else:
        lines.append("    await page.goto('/profile');")
        lines.append(f"    await page.getByLabel('Full name').fill('{name}');")
        lines.append("    await page.getByRole('button', { name: /save/i }).click();")
        lines.append("    await expect(page.getByTestId('save-success')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Signup family ---
def gen_signup(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    name = NAMES[variant % len(NAMES)]
    email = EMAILS[variant % len(EMAILS)]
    sub = variant // len(EMAILS)
    patterns = [
        ("positive", f"Write a test for registering a new user named '{name}'"),
        ("negative", f"Write a test showing validation errors when registration fields are invalid"),
    ]
    label, desc = patterns[sub % len(patterns)]
    has_email = use_utils and "generateRandomEmail" in utils
    has_str = use_utils and "generateRandomString" in utils
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Registration", () => {', ""]
    if label == "positive":
        lines.append(f'  test("should register {name}", async ({{ page }}) => {{')
        if "SignupPage" in pos:
            s = pv("SignupPage")
            lines.append(f"    const {s} = new SignupPage(page);")
            lines.append(f"    await {s}.goto();")
            email_val = "generateRandomEmail()" if has_email else f"'{email}'"
            lines.append(f"    const newEmail = {email_val};")
            pw = "generateRandomString(12)" if has_str else "'SecurePass1!'"
            lines.append(f"    const password = {pw};")
            lines.append(f"    await {s}.fillForm('{name}', newEmail, password);")
            lines.append(f"    await {s}.termsCheckbox.check();")
            lines.append(f"    await {s}.submit();")
            lines.append(f"    await expect({s}.successMessage).toBeVisible();")
        else:
            lines.append("    await page.goto('/signup');")
            lines.append(f"    await page.getByLabel('Full name').fill('{name}');")
            lines.append(f"    await page.getByLabel('Email').fill('{email}');")
            lines.append("    await page.getByLabel('Create password').fill('SecurePass1!');")
            lines.append("    await page.getByLabel('Confirm password').fill('SecurePass1!');")
            lines.append("    await page.getByRole('checkbox', { name: /terms/i }).check();")
            lines.append("    await page.getByRole('button', { name: /create account/i }).click();")
            lines.append("    await expect(page.getByTestId('signup-success')).toBeVisible();")
        lines.append("  });")
    else:
        lines.append(f'  test("should show validation errors", async ({{ page }}) => {{')
        if "SignupPage" in pos:
            s = pv("SignupPage")
            lines.append(f"    const {s} = new SignupPage(page);")
            lines.append(f"    await {s}.goto();")
            lines.append(f"    await {s}.fillForm('T', 'invalid', '1');")
            lines.append(f"    await {s}.submit();")
            lines.append("    await expect(page.getByText(/error|invalid|required/i)).toBeVisible();")
        else:
            lines.append("    await page.goto('/signup');")
            lines.append("    await page.getByRole('button', { name: /create account/i }).click();")
            lines.append("    await expect(page.getByText(/required|invalid|error/i)).toBeVisible();")
        lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Search family ---
def gen_search(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    query = QUERIES[variant % len(QUERIES)]
    filter_ = FILTERS[variant % len(FILTERS)]
    sub = variant // len(QUERIES)
    patterns = [
        ("positive", f"Write a test for searching '{query}' and verifying results"),
        ("positive", f"Write a test for filtering search results by '{filter_}'"),
        ("negative", f"Write a test showing no results for an unusual search query"),
    ]
    label, desc = patterns[sub % len(patterns)]
    cred = LOGIN_CREDS[variant % len(LOGIN_CREDS)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Search", () => {', ""]
    if use_utils and "loginAs" in utils or "LoginPage" in pos:
        lines.append("  test.beforeEach(async ({ page }) => {")
        if use_utils and "loginAs" in utils:
            lines.append(f"    await loginAs(page, '{cred[0]}', '{cred[1]}');")
        elif "LoginPage" in pos:
            l = pv("LoginPage")
            lines.append(f"    const {l} = new LoginPage(page);")
            lines.append(f"    await {l}.login('{cred[0]}', '{cred[1]}');")
        lines.append("  });\n")
    lines.append(f'  test("{desc}", async ({{ page }}) => {{')
    if "no results" in desc:
        q = "zzzxxxxxxxnonsense"
    else:
        q = query
    if "DashboardPage" in pos:
        d = pv("DashboardPage")
        lines.append(f"    const {d} = new DashboardPage(page);")
        lines.append(f"    await {d}.search('{q}');")
    elif "SearchResultsPage" in pos:
        sr = pv("SearchResultsPage")
        lines.append(f"    const {sr} = new SearchResultsPage(page);")
        lines.append(f"    await {sr}.goto('{q}');")
    else:
        lines.append(f"    await page.goto('/search?q={q}');")
    if "filter" in desc and "SearchResultsPage" in pos:
        sr = pv("SearchResultsPage")
        lines.append(f"    await {sr}.applyFilter('{filter_}');")
    if "no results" in desc:
        if "SearchResultsPage" in pos:
            sr = pv("SearchResultsPage")
            lines.append(f"    await expect({sr}.noResultsMessage).toBeVisible();")
        else:
            lines.append("    await expect(page.getByTestId('no-results')).toBeVisible();")
    elif "SearchResultsPage" in pos:
        sr = pv("SearchResultsPage")
        lines.append(f"    await expect({sr}.resultsList).toBeVisible();")
        if "filter" in desc:
            lines.append(f"    await expect({sr}.resultItems.first()).toBeVisible();")
    else:
        lines.append("    await expect(page.getByTestId('search-results')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Payment family ---
def gen_payment(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    card = CARDS[variant % len(CARDS)]
    sub = variant // len(CARDS)
    patterns = [
        ("positive", f"Write a test for paying with card ending in {card[0][-4:]}"),
        ("positive", f"Write a test for successful payment and confirmation message"),
    ]
    label, desc = patterns[sub % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Payment", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append("    await loginAs(page, 'user@example.com', 'Password123!');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append("    await loginPage.login('user@example.com', 'Password123!');")
    else:
        lines.append("    await page.goto('/login');")
        lines.append("    await page.getByLabel('Email address').fill('user@example.com');")
        lines.append("    await page.getByLabel('Password').fill('Password123!');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("should complete payment", async ({{ page }}) => {{')
    if "PaymentPage" in pos:
        pm = pv("PaymentPage")
        lines.append(f"    const {pm} = new PaymentPage(page);")
        lines.append(f"    await {pm}.goto();")
        lines.append(f"    await {pm}.fillCardDetails('{card[0]}', '{card[1]}', '{card[2]}', 'Test User');")
        lines.append(f"    await {pm}.pay();")
        lines.append(f"    await expect({pm}.successMessage).toBeVisible();")
    else:
        lines.append("    await page.goto('/payment');")
        lines.append(f"    await page.getByPlaceholder('Card number').fill('{card[0]}');")
        lines.append(f"    await page.getByPlaceholder('MM/YY').fill('{card[1]}');")
        lines.append(f"    await page.getByPlaceholder('CVV').fill('{card[2]}');")
        lines.append("    await page.getByLabel('Name on card').fill('Test User');")
        lines.append("    await page.getByRole('button', { name: /pay/i }).click();")
        lines.append("    await expect(page.getByTestId('payment-success')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)

def gen_payment_error(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    card = EXPIRED_CARDS[variant % len(EXPIRED_CARDS)]
    patterns = [
        ("negative", f"Write a test for payment with expired card {card[0][-4:]}"),
        ("negative", f"Write a test for declined card payment"),
    ]
    label, desc = patterns[variant % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Payment Errors", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append("    await loginAs(page, 'user@example.com', 'Password123!');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append("    await loginPage.login('user@example.com', 'Password123!');")
    else:
        lines.append("    await page.getByLabel('Email address').fill('user@example.com');")
        lines.append("    await page.getByLabel('Password').fill('Password123!');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("should reject payment", async ({{ page }}) => {{')
    if "PaymentPage" in pos:
        pm = pv("PaymentPage")
        lines.append(f"    const {pm} = new PaymentPage(page);")
        lines.append(f"    await {pm}.goto();")
        lines.append(f"    await {pm}.fillCardDetails('{card[0]}', '{card[1]}', '{card[2]}', 'Test User');")
        lines.append(f"    await {pm}.pay();")
        lines.append(f"    await expect({pm}.errorMessage).toBeVisible();")
    else:
        lines.append("    await page.goto('/payment');")
        lines.append(f"    await page.getByPlaceholder('Card number').fill('{card[0]}');")
        lines.append(f"    await page.getByPlaceholder('MM/YY').fill('{card[1]}');")
        lines.append(f"    await page.getByPlaceholder('CVV').fill('{card[2]}');")
        lines.append("    await page.getByRole('button', { name: /pay/i }).click();")
        lines.append("    await expect(page.getByTestId('payment-error')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Settings family ---
def gen_settings(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    theme = THEMES[variant % len(THEMES)]
    lang = LANGS[variant % len(LANGS)]
    sub = variant // max(len(THEMES), len(LANGS))
    patterns = [
        ("positive", f"Write a test for changing theme to '{theme}'"),
        ("positive", f"Write a test for changing language to '{lang}'"),
        ("positive", f"Write a test for toggling notification settings"),
    ]
    label, desc = patterns[sub % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Settings", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append("    await loginAs(page, 'user@example.com', 'Password123!');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append("    await loginPage.login('user@example.com', 'Password123!');")
    else:
        lines.append("    await page.getByLabel('Email address').fill('user@example.com');")
        lines.append("    await page.getByLabel('Password').fill('Password123!');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("should update settings", async ({{ page }}) => {{')
    if "SettingsPage" in pos:
        st = pv("SettingsPage")
        lines.append(f"    const {st} = new SettingsPage(page);")
        lines.append(f"    await {st}.goto();")
        if "theme" in desc:
            lines.append(f"    await {st}.themeSelect.selectOption('{theme}');")
        elif "language" in desc:
            lines.append(f"    await {st}.languageSelect.selectOption('{lang}');")
        elif "notification" in desc:
            lines.append(f"    await {st}.notificationsToggle.click();")
        lines.append(f"    await {st}.saveButton.click();")
        lines.append(f"    await expect({st}.successMessage).toBeVisible();")
    else:
        lines.append("    await page.goto('/settings');")
        if "theme" in desc:
            lines.append(f"    await page.getByLabel('Theme').selectOption('{theme}');")
        elif "language" in desc:
            lines.append(f"    await page.getByLabel('Language').selectOption('{lang}');")
        elif "notification" in desc:
            lines.append("    await page.getByRole('switch', { name: /notifications/i }).click();")
        lines.append("    await page.getByRole('button', { name: /save settings/i }).click();")
        lines.append("    await expect(page.getByTestId('settings-saved')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Admin family ---
def gen_admin(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    cred = ADMIN_CREDS[variant % len(ADMIN_CREDS)]
    name = NAMES[variant % len(NAMES)]
    email = EMAILS[variant % len(EMAILS)]
    sub = variant // max(len(ADMIN_CREDS), len(EMAILS))
    patterns = [
        ("positive", f"Write a test for admin adding user '{name}'"),
        ("positive", f"Write a test for admin deleting user '{email}'"),
    ]
    label, desc = patterns[sub % len(patterns)]
    has_email_util = use_utils and "generateRandomEmail" in utils
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Admin", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append(f"    await loginAs(page, '{cred[0]}', '{cred[1]}');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append(f"    await {l}.login('{cred[0]}', '{cred[1]}');")
    else:
        lines.append(f"    await page.getByLabel('Email address').fill('{cred[0]}');")
        lines.append(f"    await page.getByLabel('Password').fill('{cred[1]}');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("{desc}", async ({{ page }}) => {{')
    if "AdminUserListPage" in pos:
        a = pv("AdminUserListPage")
        lines.append(f"    const {a} = new AdminUserListPage(page);")
        lines.append(f"    await {a}.goto();")
        if "adding" in desc:
            lines.append(f"    await {a}.addUserButton.click();")
            if has_email_util:
                lines.append("    const newEmail = generateRandomEmail();")
            else:
                lines.append(f"    const newEmail = '{email}';")
            lines.append("    await page.getByLabel('Email').fill(newEmail);")
            lines.append(f"    await page.getByLabel('Name').fill('{name}');")
            lines.append("    await page.getByRole('button', { name: /save/i }).click();")
            lines.append(f"    await expect({a}.successMessage).toBeVisible();")
        elif "deleting" in desc:
            lines.append(f"    await {a}.deleteUser('{email}');")
            lines.append(f"    await {a}.confirmDelete.click();")
            lines.append(f"    await expect({a}.successMessage).toBeVisible();")
    else:
        lines.append("    await page.goto('/admin/users');")
        if "adding" in desc:
            lines.append("    await page.getByRole('button', { name: /add user/i }).click();")
            lines.append(f"    await page.getByLabel('Email').fill('{email}');")
            lines.append(f"    await page.getByLabel('Name').fill('{name}');")
            lines.append("    await page.getByRole('button', { name: /save/i }).click();")
            lines.append("    await expect(page.getByTestId('action-success')).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Navigation family ---
def gen_nav(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    patterns = [
        ("positive", "Write a test for navigating from dashboard to profile and back"),
        ("positive", "Write a test for verifying sidebar navigation links are visible"),
    ]
    label, desc = patterns[variant % len(patterns)]
    lines = [imports(pos, utils, use_utils), "",
             'test.describe("Navigation", () => {', ""]
    lines.append("  test.beforeEach(async ({ page }) => {")
    if use_utils and "loginAs" in utils:
        lines.append("    await loginAs(page, 'user@example.com', 'Password123!');")
    elif "LoginPage" in pos:
        l = pv("LoginPage")
        lines.append(f"    const {l} = new LoginPage(page);")
        lines.append("    await loginPage.login('user@example.com', 'Password123!');")
    else:
        lines.append("    await page.getByLabel('Email address').fill('user@example.com');")
        lines.append("    await page.getByLabel('Password').fill('Password123!');")
        lines.append("    await page.getByRole('button', { name: /sign in/i }).click();")
    lines.append("  });\n")
    lines.append(f'  test("{desc}", async ({{ page }}) => {{')
    if "sidebar" in desc and "DashboardPage" in pos:
        d = pv("DashboardPage")
        lines.append(f"    const {d} = new DashboardPage(page);")
        lines.append(f"    await expect({d}.navSidebar).toBeVisible();")
    elif "DashboardPage" in pos:
        d = pv("DashboardPage")
        lines.append(f"    const {d} = new DashboardPage(page);")
        lines.append(f"    await {d}.profileLink.click();")
        lines.append("    await expect(page).toHaveURL(/.*profile/);")
        if "ProfilePage" in pos:
            pp = pv("ProfilePage")
            lines.append(f"    const {pp} = new ProfilePage(page);")
            lines.append(f"    await expect({pp}.nameInput).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# --- Raw Playwright boundary tests ---
def gen_raw(pos: List[str], utils: List[str], use_utils: bool, variant: int) -> Tuple[str, str, str]:
    patterns = [
        ("negative", "Write a test for file upload with file exceeding size limit"),
        ("negative", "Write a test for form submission with empty required fields"),
        ("negative", "Write a test verifying error message on password mismatch during signup"),
    ]
    label, desc = patterns[variant % len(patterns)]
    lines = [imports([], [], False), "",
             'test.describe("Boundary conditions", () => {', ""]
    lines.append(f'  test("{desc}", async ({{ page }}) => {{')
    if "upload" in desc:
        lines.append("    await page.goto('/upload');")
        lines.append("    const fileChooser = page.waitForEvent('filechooser');")
        lines.append("    await page.getByRole('button', { name: /upload/i }).click();")
        lines.append("    await fileChooser.then(fc => fc.setFiles('tests/fixtures/large-file.pdf'));")
        lines.append("    await expect(page.getByTestId('upload-error')).toContainText(/too large|exceeds/i);")
    elif "empty required" in desc:
        lines.append("    await page.goto('/signup');")
        lines.append("    await page.getByRole('button', { name: /create account/i }).click();")
        lines.append("    await expect(page.getByText(/required|invalid|error/i)).toBeVisible();")
    elif "password mismatch" in desc:
        lines.append("    await page.goto('/signup');")
        lines.append("    await page.getByLabel('Full name').fill('Test User');")
        lines.append("    await page.getByLabel('Email').fill('test@example.com');")
        lines.append("    await page.getByLabel('Create password').fill('Pass123!');")
        lines.append("    await page.getByLabel('Confirm password').fill('Different!');")
        lines.append("    await page.getByRole('button', { name: /create account/i }).click();")
        lines.append("    await expect(page.getByText(/match|mismatch|confirm/i)).toBeVisible();")
    lines.append("  });")
    lines.append("});")
    return ("\n".join(lines), label, desc)


# ---------------------------------------------------------------------------
# Define all families with PO and util combinations
# ---------------------------------------------------------------------------

FAMILIES: List[Family] = [
    Family("login", "auth", [["LoginPage", "DashboardPage"], ["LoginPage"], [], ["LoginPage", "DashboardPage"]],
           [["loginAs", "waitForPageLoad"], ["loginAs"], [], ["waitForPageLoad"]], gen_login),
    Family("login_error", "auth", [["LoginPage"], [], ["LoginPage"]], [[], [], []], gen_login_error),
    Family("logout", "auth", [["LoginPage", "DashboardPage"], ["LoginPage"], [], ["LoginPage", "DashboardPage"]],
           [["loginAs", "logout"], ["loginAs"], [], ["logout"]], gen_logout),
    Family("profile", "form", [["ProfilePage", "LoginPage"], ["ProfilePage"], [], ["ProfilePage"]],
           [["loginAs", "clearAndFill", "generateRandomEmail"], ["loginAs", "clearAndFill"], ["loginAs"], []], gen_profile),
    Family("signup", "auth", [["SignupPage"], [], ["SignupPage"]],
           [["generateRandomEmail", "generateRandomString"], ["generateRandomEmail"], []], gen_signup),
    Family("search", "search", [["DashboardPage", "SearchResultsPage", "LoginPage"],
                                 ["SearchResultsPage"], ["SearchResultsPage", "LoginPage"], []],
           [["loginAs"], [], ["loginAs"], []], gen_search),
    Family("payment", "payment", [["PaymentPage", "LoginPage"], ["PaymentPage"], [], ["PaymentPage"]],
           [["loginAs"], [], ["loginAs"], []], gen_payment),
    Family("payment_error", "payment", [["PaymentPage", "LoginPage"], ["PaymentPage"], []],
           [["loginAs"], [], []], gen_payment_error),
    Family("settings", "form", [["SettingsPage", "LoginPage"], ["SettingsPage"], []],
           [["loginAs"], [], []], gen_settings),
    Family("admin", "crud", [["AdminUserListPage", "LoginPage"], ["AdminUserListPage"], []],
           [["loginAs", "generateRandomEmail"], ["loginAs"], []], gen_admin),
    Family("navigation", "navigation", [["DashboardPage", "ProfilePage", "LoginPage"],
                                         ["DashboardPage", "ProfilePage"], ["DashboardPage"]],
           [["loginAs"], [], []], gen_nav),
    Family("raw", "form", [[]], [[]], gen_raw),
]


# ---------------------------------------------------------------------------
# Type A generator
# ---------------------------------------------------------------------------

def generate_type_a(family: Family, pos: List[str], utils: List[str], use_utils: bool, variant: int) -> dict:
    code, ttype, desc = family.code_gen(pos, utils, use_utils, variant)
    user_msg = build_user_message(pos, utils, desc, use_utils=use_utils)
    return {
        "messages": [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": code},
        ],
        "metadata": {
            "type": "single_turn", "family": family.name,
            "feature_type": family.feature_type, "test_type": ttype,
            "uses_utilities": use_utils and bool(utils),
            "uses_page_objects": bool(pos),
            "page_objects": pos, "utilities": utils,
            "source": "synthetic_v2",
        },
    }


# ---------------------------------------------------------------------------
# Type B: node-graph-aligned multi-turn generator
#
# Conversations follow the SDET node graph (N0–N15) with strict user/assistant
# alternation. Consecutive agent-only nodes are combined into single messages.
# Three path variants per combo: no-clarify/accept, clarify/accept,
# no-clarify/revise/accept.
# ---------------------------------------------------------------------------


def _action_summary(name: str) -> str:
    m = {
        "login": "navigating to the login page, entering credentials, and verifying the dashboard",
        "login_error": "attempting login with invalid credentials and checking the error message",
        "logout": "logging in, performing logout, and confirming the redirect to the login page",
        "profile": "navigating to the profile page and updating user profile information",
        "signup": "registering a new user through the signup form with validation",
        "search": "performing a search query and verifying the results display correctly",
        "payment": "completing a payment transaction and verifying the success confirmation",
        "payment_error": "submitting payment with invalid card details and verifying the error",
        "settings": "updating user preferences and verifying the settings are saved",
        "admin": "performing admin CRUD operations on the user management page",
        "navigation": "navigating between pages and verifying the correct page loads",
        "raw": "testing boundary conditions and edge case scenarios",
    }
    return m.get(name, "performing the described user flow")


def _short_desc(desc: str) -> str:
    for p in ["Write a test for ", "Write a test showing ", "Write a test verifying "]:
        if desc.startswith(p):
            return desc[len(p):]
    return desc


def _node_analysis(family, ttype, po_names, util_names, desc):
    return (
        f"[N2] Let me analyze this test scenario.\n\n"
        f"**Feature:** {family.name}\n"
        f"**Test type:** {ttype}\n"
        f"**Page objects available:** {po_names}\n"
        f"**Utilities available:** {util_names}\n\n"
        f"The user wants to {_short_desc(desc)}. "
        f"This involves {_action_summary(family.name)}."
    )


def _node_clarify(desc):
    return (
        f"[N3] I want to make sure I understand correctly.\n\n"
        f"Could you clarify:\n"
        f"1. What page or screen does this test start from?\n"
        f"2. What specific action triggers the scenario?\n"
        f"3. What outcome should the assertion verify?\n\n"
        f"This will help me build the right test for: {_short_desc(desc)}"
    )


def _node_intent(ttype, family_name):
    return (
        f"[N5] Thanks! I've determined this is a **{ttype}** test for {family_name}. "
        f"The test should verify correct behavior under {ttype} conditions."
    )


def _node_test_type_question():
    return (
        f"[N6] To choose the right approach, please confirm the test type:\n\n"
        f"- **positive** (happy path)\n"
        f"- **negative** (invalid input / error)\n"
        f"- **edge** (boundary conditions)\n"
        f"- **error_handling** (server errors, timeouts)\n"
        f"- **permission** (access control)"
    )


def _node_journey(family_name, ttype, desc):
    return (
        f"[N7] I have a clear picture now. The user journey involves:\n\n"
        f"1. **Setup** — Navigate to the relevant page and establish preconditions\n"
        f"2. **Action** — {_short_desc(desc)}\n"
        f"3. **Verification** — Assert the {ttype} outcome at each checkpoint"
    )


def _node_feature_question():
    return (
        f"[N8] To apply the right test patterns, what feature category does this belong to?\n\n"
        f"- **auth** (authentication, login, signup)\n"
        f"- **form** (form submission, data entry)\n"
        f"- **crud** (create, read, update, delete)\n"
        f"- **navigation** (page transitions, routing)\n"
        f"- **search** (search, filter, query)\n"
        f"- **payment** (checkout, billing, transaction)\n"
        f"- **notification** (alerts, toasts, messages)\n"
        f"- **media** (uploads, files, images)"
    )


def _node_technical_plan(pos, utils, code):
    po_details = ", ".join(pos) if pos else "raw Playwright locators"
    return (
        f"[N9] Now let me identify the page elements we need.\n"
        f"[N10] I'll use Playwright's built-in locators for reliability.\n"
        f"[N11] **Action plan:** Using page objects: {po_details}\n"
        f"[N12] **Assertions:** Verifying key behavioral states\n"
        f"[N13] **Reliability:** Adding proper waits and error handling\n\n"
        f"[N14] Here's the complete test:\n\n"
        f"```typescript\n{code}\n```"
    )


def _node_review():
    return (
        f"[N15] Here's the generated test. Does this look good?\n\n"
        f"- **Accept** if you're satisfied\n"
        f"- **Request changes** if modifications are needed\n"
        f"- **Start over** for a different approach"
    )


def _node_revise(family, pos, utils, code):
    po_details = ", ".join(pos) if pos else "raw Playwright locators"
    return (
        f"I'll revise the test based on your feedback.\n\n"
        f"[N7] Re-examining the user journey...\n"
        f"[N8] Adjusting the feature approach for {po_details}...\n\n"
        f"[N9-N14] Here's the updated test:\n\n"
        f"```typescript\n{code}\n```\n\n"
        f"[N15] Does this updated version work for you?"
    )


def _path_no_clarify_accept(family, pos, utils, code, ttype, desc, use_utils, data_variant=0) -> dict:
    """10 messages (5 turns): no clarify cycle, accept at N15."""
    user_msg = build_user_message(pos, utils, desc, use_utils=use_utils)
    po_names = ", ".join(pos) if pos else "none (raw Playwright)"
    util_names = ", ".join(utils) if utils else "none"
    return {
        "messages": [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": _node_analysis(family, ttype, po_names, util_names, desc) + "\n\n" + _node_clarify(desc)},
            {"role": "user", "content": random.choice(["Yes, that's correct. Proceed with the test.", "That's right, go ahead.", "Correct. Please continue.", "Yes, you've understood correctly. Proceed."])},
            {"role": "assistant", "content": _node_intent(ttype, family.name) + "\n\n" + _node_test_type_question()},
            {"role": "user", "content": ttype},
            {"role": "assistant", "content": _node_journey(family.name, ttype, desc) + "\n\n" + _node_feature_question()},
            {"role": "user", "content": family.feature_type},
            {"role": "assistant", "content": _node_technical_plan(pos, utils, code) + "\n\n" + _node_review()},
            {"role": "user", "content": random.choice(["Looks good, accept.", "This looks correct. Accept.", "Great, I accept the test.", "Perfect. Accept."])},
            {"role": "assistant", "content": "Test generation complete! The test has been saved and is ready for execution. You can start a new session to create another test."},
        ],
        "metadata": {
            "type": "multi_turn", "family": family.name,
            "feature_type": family.feature_type, "test_type": ttype,
            "uses_utilities": use_utils and bool(utils),
            "uses_page_objects": bool(pos),
            "page_objects": pos, "utilities": utils,
            "source": "synthetic_v2",
            "variant": "no_clarify_accept",
            "turn_count": 5, "message_count": 10,
        },
    }


def _path_clarify_accept(family, pos, utils, code, ttype, desc, use_utils, data_variant=0) -> dict:
    """12 messages (6 turns): clarify once at N3, then accept at N15."""
    user_msg = build_user_message(pos, utils, desc, use_utils=use_utils)
    po_names = ", ".join(pos) if pos else "none (raw Playwright)"
    util_names = ", ".join(utils) if utils else "none"
    clarify_detail = f"I need a {ttype} test for {family.name}. Specifically, {_short_desc(desc)}. The user navigates to the relevant page and we verify the outcome."
    return {
        "messages": [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": _node_analysis(family, ttype, po_names, util_names, desc) + "\n\n" + _node_clarify(desc)},
            {"role": "user", "content": random.choice(["Let me explain more clearly.", "I'm not sure I was clear enough. Let me elaborate:", "Actually, let me give you more detail:"]) + "\n\n" + clarify_detail},
            {"role": "assistant", "content": "[N2] Thanks for the clarification. Let me re-analyze with this additional context.\n\n" + _node_clarify("confirming understanding of " + _short_desc(desc))},
            {"role": "user", "content": random.choice(["Yes, that's correct now. Proceed.", "Right, you've got it. Please continue.", "Yes, that's what I meant. Go ahead."])},
            {"role": "assistant", "content": _node_intent(ttype, family.name) + "\n\n" + _node_test_type_question()},
            {"role": "user", "content": ttype},
            {"role": "assistant", "content": _node_journey(family.name, ttype, desc) + "\n\n" + _node_feature_question()},
            {"role": "user", "content": family.feature_type},
            {"role": "assistant", "content": _node_technical_plan(pos, utils, code) + "\n\n" + _node_review()},
            {"role": "user", "content": random.choice(["Looks good, accept.", "This looks correct. Accept.", "Great, I accept the test."])},
            {"role": "assistant", "content": "Test generation complete! The test has been saved and is ready for execution."},
        ],
        "metadata": {
            "type": "multi_turn", "family": family.name,
            "feature_type": family.feature_type, "test_type": ttype,
            "uses_utilities": use_utils and bool(utils),
            "uses_page_objects": bool(pos),
            "page_objects": pos, "utilities": utils,
            "source": "synthetic_v2",
            "variant": "clarify_accept",
            "turn_count": 6, "message_count": 12,
        },
    }


def _path_no_clarify_revise_accept(family, pos, utils, code, ttype, desc, use_utils, data_variant=0) -> dict:
    """12 messages (6 turns): no clarify, revise once at N15, then accept."""
    user_msg = build_user_message(pos, utils, desc, use_utils=use_utils)
    po_names = ", ".join(pos) if pos else "none (raw Playwright)"
    util_names = ", ".join(utils) if utils else "none"
    revised_code, _rttype, _rdesc = family.code_gen(pos, utils, use_utils, variant=data_variant + 100)
    return {
        "messages": [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": _node_analysis(family, ttype, po_names, util_names, desc) + "\n\n" + _node_clarify(desc)},
            {"role": "user", "content": random.choice(["Yes, that's correct. Proceed.", "That's right, go ahead.", "Correct. Please continue."])},
            {"role": "assistant", "content": _node_intent(ttype, family.name) + "\n\n" + _node_test_type_question()},
            {"role": "user", "content": ttype},
            {"role": "assistant", "content": _node_journey(family.name, ttype, desc) + "\n\n" + _node_feature_question()},
            {"role": "user", "content": family.feature_type},
            {"role": "assistant", "content": _node_technical_plan(pos, utils, code) + "\n\n" + _node_review()},
            {"role": "user", "content": random.choice(["I need some changes. Add more assertions for edge cases.", "Please revise the test — add better error handling.", "Can you update this? I'd like more comprehensive assertions."])},
            {"role": "assistant", "content": _node_revise(family, pos, utils, revised_code)},
            {"role": "user", "content": random.choice(["Yes, that's better. Accept.", "Great, the revised version looks good. Accept.", "This works now. Accept."])},
            {"role": "assistant", "content": "Test generation complete! The revised test has been saved and is ready for execution."},
        ],
        "metadata": {
            "type": "multi_turn", "family": family.name,
            "feature_type": family.feature_type, "test_type": ttype,
            "uses_utilities": use_utils and bool(utils),
            "uses_page_objects": bool(pos),
            "page_objects": pos, "utilities": utils,
            "source": "synthetic_v2",
            "variant": "no_clarify_revise_accept",
            "turn_count": 6, "message_count": 12,
        },
    }


_PATH_GENERATORS = [_path_no_clarify_accept, _path_clarify_accept, _path_no_clarify_revise_accept]


def generate_type_b(family: Family, pos: List[str], utils: List[str], use_utils: bool, data_variant: int, path_index: int) -> dict:
    code, ttype, desc = family.code_gen(pos, utils, use_utils, data_variant)
    generator = _PATH_GENERATORS[path_index % len(_PATH_GENERATORS)]
    return generator(family, pos, utils, code, ttype, desc, use_utils, data_variant=data_variant)


# ---------------------------------------------------------------------------
# Main: iterate all families × PO combos × util combos × data variants × use_utils
# ---------------------------------------------------------------------------

def main():
    output_dir = "/Users/skaparwan/Documents/sdet-training-data"
    os.makedirs(output_dir, exist_ok=True)
    examples: List[dict] = []
    data_variants = 12  # Number of data permutations per combo

    for family in FAMILIES:
        for pos in family.po_combos:
            for utils in family.util_combos:
                for variant in range(data_variants):
                    ex = generate_type_a(family, pos, utils, use_utils=True, variant=variant)
                    examples.append(ex)
                    # Raw Playwright variant
                    if utils:
                        raw = generate_type_a(family, pos, utils, use_utils=False, variant=variant)
                        examples.append(raw)

    # Type B: full combinatorial coverage matching Type A
    b_paths = 3
    for family in FAMILIES:
        for pos in family.po_combos:
            for utils in family.util_combos:
                for data_variant in range(data_variants):
                    for path_index in range(b_paths):
                        ex = generate_type_b(family, pos, utils, use_utils=True, data_variant=data_variant, path_index=path_index)
                        examples.append(ex)
                    if utils:
                        for path_index in range(b_paths):
                            raw_b = generate_type_b(family, pos, utils, use_utils=False, data_variant=data_variant, path_index=path_index)
                            examples.append(raw_b)

    random.shuffle(examples)

    output_file = f"{output_dir}/sdet-training-data-v2.jsonl"
    with open(output_file, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    total = len(examples)
    type_a = sum(1 for e in examples if e["metadata"]["type"] == "single_turn")
    type_b = sum(1 for e in examples if e["metadata"]["type"] == "multi_turn")
    with_utils = sum(1 for e in examples if e["metadata"]["uses_utilities"])
    families: Dict[str, int] = {}
    for e in examples:
        f = e["metadata"]["family"]
        families[f] = families.get(f, 0) + 1

    variants: Dict[str, int] = {}
    for e in examples:
        v = e["metadata"].get("variant", "unknown")
        variants[v] = variants.get(v, 0) + 1

    print(f"Generated {total} training examples")
    print(f"  Type A (single-turn): {type_a}")
    print(f"  Type B (multi-turn): {type_b}")
    if variants:
        print(f"  Type B variants: {dict(sorted(variants.items()))}")
    print(f"  With utilities: {with_utils}")
    print(f"  Families: {dict(sorted(families.items()))}")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    main()
