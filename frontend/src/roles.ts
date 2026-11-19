// Role names and what each role may do, in plain words. This mirrors the backend's permission
// policy (sentinel.shared.authz.ROLE_PERMISSIONS) for display only: the server enforces it on
// every request, and the browser grants nothing.
import type { Role } from "./api";

export const ROLE_INFO: Record<Role, { label: string; summary: string; can: string[] }> = {
  ANALYST: {
    label: "Analyst",
    summary: "Uploads, validates, requests waivers, submits for review",
    can: [
      "Upload supplier and invoice files and run validation",
      "Add investigation notes and request waivers",
      "Submit a version for review",
      "Publish an approved, eligible version and export publications",
      "Download raw uploaded files",
    ],
  },
  APPROVER: {
    label: "Approver",
    summary: "Decides waivers and reviews",
    can: [
      "Grant or deny waivers requested by someone else",
      "Approve or reject reviews submitted by someone else",
      "Add investigation notes",
      "Publish an approved, eligible version and export publications",
      "Download raw uploaded files",
    ],
  },
  ADMIN: {
    label: "Administrator",
    summary: "Manages users and configuration",
    can: ["Create users, change their roles and deactivate them", "Reload the rule configuration", "Check publication eligibility and export publications"],
  },
};

export const roleLabel = (role: string): string => ROLE_INFO[role as Role]?.label ?? role;
