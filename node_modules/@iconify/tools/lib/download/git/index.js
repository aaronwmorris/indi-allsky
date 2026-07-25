import { prepareDirectoryForExport } from "../../export/helpers/prepare.js";
import { execAsync } from "../../misc/exec.js";
import { getGitRepoBranch } from "./branch.js";
import { getGitRepoHash } from "./hash.js";
import { resetGitRepoContents } from "./reset.js";

async function downloadGitRepo(options) {
	const { remote, branch } = options;
	const hasHashInTarget = options.target.includes("{hash}");
	const ifModifiedSince = options.ifModifiedSince;
	if (ifModifiedSince || hasHashInTarget) {
		const latestHash = (await execAsync(`git ls-remote ${remote} --branch ${branch}`)).stdout.split(/\s/).shift();
		if (hasHashInTarget) options.target = options.target.replace("{hash}", latestHash);
		try {
			await getGitRepoBranch(options, branch);
			if (ifModifiedSince) {
				if (latestHash === (ifModifiedSince === true ? await getGitRepoHash(options) : typeof ifModifiedSince === "string" ? ifModifiedSince : ifModifiedSince.downloadType === "git" ? ifModifiedSince.hash : null)) {
					await resetGitRepoContents(options.target);
					return "not_modified";
				}
			}
		} catch {}
	}
	const target = options.target = await prepareDirectoryForExport({
		...options,
		cleanup: true
	});
	if (options.log) console.log(`Cloning ${remote}#${branch} to ${target}`);
	await execAsync(`git clone --branch ${branch} --no-tags --depth 1 ${remote} "${target}"`);
	const hash = await getGitRepoHash(options);
	await getGitRepoBranch(options, branch);
	return {
		downloadType: "git",
		contentsDir: target,
		hash
	};
}

export { downloadGitRepo };