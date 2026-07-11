import { test, expect } from "@playwright/test";
import { CareersPage } from "./pages/CareersPage";

test.describe("Careers - Submit Application form", () => {
  let careersPage: CareersPage;

  const applicant = {
    role: "fullstack",
    firstName: "Himanshu",
    lastName: "Bahuguna",
    email: "jdoe@example.com",
    linkedIn: "https://www.linkedin.com/in/himanshu-bahuguna-latest/",
    coverLetter:
      "I am excited to apply for the Freelance Full-Stack Developer role. " +
      "With hands-on experience building resilient CI pipelines and end-to-end " +
      "test automation, I would love to help TestRadius eliminate flaky tests.",
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

  test("submits an application for the Freelance Full-Stack Developer role", async ({
    page,
  }) => {
    const roleSelect = careersPage.getRoleSelect();
    await expect(roleSelect).toBeVisible();
    await expect(roleSelect).toBeEnabled();
    await roleSelect.selectOption(applicant.role);
    await expect(roleSelect).toHaveValue(applicant.role);

    const firstName = careersPage.getFirstNameInput();
    await expect(firstName).toBeVisible();
    await firstName.fill(applicant.firstName);
    await expect(firstName).toHaveValue(applicant.firstName);

    const lastName = careersPage.getLastNameInput();
    await expect(lastName).toBeVisible();
    await lastName.fill(applicant.lastName);
    await expect(lastName).toHaveValue(applicant.lastName);

    const email = careersPage.getEmailInput();
    await expect(email).toBeVisible();
    await email.fill(applicant.email);
    await expect(email).toHaveValue(applicant.email);

    const portfolio = careersPage.getPortfolioInput();
    await expect(portfolio).toBeVisible();
    await portfolio.fill(applicant.linkedIn);
    await expect(portfolio).toHaveValue(applicant.linkedIn);

    const coverLetter = careersPage.getCoverLetterTextarea();
    await expect(coverLetter).toBeVisible();
    await coverLetter.fill(applicant.coverLetter);
    await expect(coverLetter).toHaveValue(applicant.coverLetter);

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
