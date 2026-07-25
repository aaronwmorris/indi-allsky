import { execAsync } from "../../misc/exec.js";

/**
* Reset Git repo contents
*/
async function resetGitRepoContents(target) {
	await execAsync("git add -A", { cwd: target });
	await execAsync("git reset --hard --quiet", { cwd: target });
}

export { resetGitRepoContents };