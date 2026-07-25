import { getFetch } from "../api/fetch.js";
import { execAsync } from "../../misc/exec.js";
import fs from "node:fs/promises";

/**
* Get version of package from NPM registry
*/
async function getNPMVersion(options) {
	const tag = options.tag || "latest";
	const packageName = options.package;
	let data;
	if (options.fetch) data = await getFetch()(`https://registry.npmjs.org/${packageName}/${tag}`).then((res) => res.json());
	else {
		const result = await execAsync(`npm view ${packageName}@${tag} --json`, { maxBuffer: 1024 * 1024 * 8 });
		data = JSON.parse(result.stdout);
	}
	return {
		version: data.version,
		file: data.dist?.tarball ?? `https://registry.npmjs.org/${packageName}/-/${packageName.split("/").pop()}-${data.version}.tgz`
	};
}
/**
* Get version of package from filename
*/
async function getPackageVersion(target) {
	return JSON.parse(await fs.readFile(target + "/package.json", "utf8")).version;
}

export { getNPMVersion, getPackageVersion };