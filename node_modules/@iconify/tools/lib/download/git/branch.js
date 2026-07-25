import { execAsync } from "../../misc/exec.js";

/**
* Get current branch from cloned git repo
*/
async function getGitRepoBranch(options, checkout) {
	const branch = (await execAsync("git branch --show-current", { cwd: options.target })).stdout.trim();
	if (typeof checkout === "string" && branch !== checkout) {
		await execAsync(`git checkout ${checkout} "${options.target}"`);
		return await getGitRepoBranch(options);
	}
	return branch;
}

export { getGitRepoBranch };