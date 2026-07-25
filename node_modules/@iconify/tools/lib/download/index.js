import { downloadGitRepo } from "./git/index.js";
import { downloadGitHubRepo } from "./github/index.js";
import { downloadGitLabRepo } from "./gitlab/index.js";
import { downloadNPMPackage } from "./npm/index.js";

function assertNever(v) {}
function downloadPackage(options) {
	switch (options.downloadType) {
		case "git": return downloadGitRepo(options);
		case "github": return downloadGitHubRepo(options);
		case "gitlab": return downloadGitLabRepo(options);
		case "npm": return downloadNPMPackage(options);
		default:
			assertNever(options);
			throw new Error(`Invalid download type: ${options.downloadType}`);
	}
}

export { downloadPackage };