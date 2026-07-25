import { sendAPIQuery } from "../api/index.js";
import { defaultGitLabBaseURI } from "./types.js";

/**
* Get latest hash from GitHub using API
*/
async function getGitLabRepoHash(options) {
	const response = await sendAPIQuery({
		uri: `${options.uri || defaultGitLabBaseURI}/${options.project}/repository/branches/${options.branch}/`,
		headers: { Authorization: "token " + options.token }
	});
	if (!response.success) throw new Error(`Error downloading data from GitLab API: ${response.error}`);
	const content = JSON.parse(response.content);
	const item = (content instanceof Array ? content : [content]).find((item) => item.name === options.branch && typeof item.commit.id === "string");
	if (!item) throw new Error("Error parsing GitLab API response");
	return item.commit.id;
}

export { getGitLabRepoHash };