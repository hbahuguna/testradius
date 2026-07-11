import { test, expect } from "@playwright/test";
import { CareersPage } from "./pages/CareersPage";

test.describe("Careers - Submit Application form (role + resume + submit)", () => {
  let careersPage: CareersPage;

  const applicant = {
    role: "fullstack",
    resumeUrl:
      "https://docs.google.com/document/d/16BrvMaPHvpAqka2xngCLORxWZNxwZWsgf-TtxlQ2QJo/edit?tab=t.0",
  };

  test.beforeEach(async ({ page }) => {
    careersPage = new CareersPage(page);
    await careersPage.goto();
    await expect(page).toHaveURL(/\/jobs$/);
    await expect(careersPage.getHeroHeading()).toBeVisible();
    await expect(careersPage.getApplicationForm()).toBeVisible();
  });

  test("selects the Freelance Full-Stack Developer role, links a resume, and submits", async ({
    page,
  }) => {
    const roleSelect = careersPage.getRoleSelect();
    await expect(roleSelect).toBeVisible();
    await expect(roleSelect).toBeEnabled();
    await roleSelect.selectOption(applicant.role);
    await expect(roleSelect).toHaveValue(applicant.role);

    const resume = careersPage.getResumeInput();
    await expect(resume).toBeVisible();
    await resume.fill(applicant.resumeUrl);
    await expect(resume).toHaveValue(applicant.resumeUrl);

    const submitButton = careersPage.getSubmitButton();
    await expect(submitButton).toBeVisible();
    await expect(submitButton).toBeEnabled();
    await submitButton.click();

    await expect(careersPage.getSuccessHeading()).toBeVisible();
    await expect(careersPage.getSubmitAnotherButton()).toBeVisible();
  });
});
