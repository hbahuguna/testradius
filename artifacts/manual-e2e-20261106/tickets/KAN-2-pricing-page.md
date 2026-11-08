# Jira Ticket (save as KAN-2): User: As visitor, I want to see pricing plans so that I can choose a plan that fits my team size

## Description
As a visitor to https://testradius.dev/pricing, I want a clear view of the five TestRadius pricing tiers, monthly vs annual billing, CTA paths, and cost estimate, so that I can pick a plan that fits my team size and start from the Free shadow-mode trial without a credit card.

Context:
- Pricing page SUT: https://testradius.dev/pricing
- Tiers shown: Free ($0/month), Starter ($79/month or $790/year billed annually, up to 5 developers), Growth (Most Popular, $25/dev/month or $250/year billed annually, 6-25 developers), Scale ($19/dev/month or $190/year billed annually, 26-75 developers), Enterprise (From $1,499/month, 75+ developers).
- Billing toggle: Pay monthly vs Pay annually with Save 17% badge.
- Also expected: comparison table (TestRadius vs Launchable vs DIY Scripts), Team Cost Calculator, FAQ accordion, money-back guarantee note (30-day on paid plans), launch pricing note valid until Dec 31, 2026.

## Acceptance Criteria
- Given I open https://testradius.dev/pricing, when the page loads, then I see five plan cards (Free $0, Starter $79, Growth labeled Most Popular, Scale $19, Enterprise From $1,499) and a Pay monthly / Pay annually toggle with Save 17% badge, with no error.
- Given I am on the pricing page, when I switch from Pay monthly to Pay annually, then prices update to the annual equivalents shown in the plan cards with no error and the page remains usable.
- Given I am on the pricing page, when I click a plan CTA (Get Started Free on the Free plan, or Start Trial on Starter/Growth/Scale, or Contact Sales on Enterprise), then the app navigates to signup/login/contact flow for that plan without showing an error.
- Given I am on the pricing page, when I expand a Frequently asked questions item, then its answer becomes visible and other items still open correctly, with no error.
- Given I am on the pricing page, when I change the Team Cost Calculator developer count, then the displayed total or plan availability updates consistently with the count, with no error.

## Steps to Reproduce / Run
1. Navigate to https://testradius.dev/pricing.
2. Verify the five plan cards and the monthly/annual toggle.
3. Toggle to annual billing and verify updated prices.
4. Scroll to FAQ section, open one question (e.g. Can I cancel anytime?), verify the answer shows.
5. Scroll to Team Cost Calculator, change developer count (e.g. to 10), verify total/plan text updates.
6. Click the Free plan CTA (Get Started Free), verify navigation to signup/login flow.
7. Verify no client-side errors appear during the flow.

## Preconditions
- No account required; visitor view of pricing page.
- Do not complete any purchase or payment; only verify CTA routing starts the signup/login/contact flow.

## Notes
- Failure signal: any plan card missing, billing toggle not updating prices, FAQ/calculator broken, or CTA click showing an error page counts as failure.
- User-facing guarantee text on the page: 30-day money-back guarantee on paid plans; Free plan is a free shadow mode trial with no credit card required.
