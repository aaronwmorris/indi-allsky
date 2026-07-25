import { execAsync } from "../../misc/exec.js";

/**
* Get latest hash from cloned git repo
*/
async function getGitRepoHash(options) {
	return (await execAsync("git rev-parse HEAD", { cwd: options.target })).stdout.trim();
}

export { getGitRepoHash };