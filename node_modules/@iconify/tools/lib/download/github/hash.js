import { sendAPIQuery } from "../api/index.js";

/**
* Get latest hash from GitHub using API
*/
async function getGitHubRepoHash(options) {
	const response = await sendAPIQuery({
		uri: `https://api.github.com/repos/${options.user}/${options.repo}/branches/${options.branch}`,
		headers: {
			Accept: "application/vnd.github.v3+json",
			Authorization: "token " + options.token
		}
	});
	if (!response.success) throw new Error(`Error downloading data from GitHub API: ${response.error}`);
	const hash = JSON.parse(response.content)?.commit?.sha;
	if (typeof hash !== "string") throw new Error("Error parsing GitHub API response");
	return hash;
}

export { getGitHubRepoHash };