import { writeJSONFile } from "../../misc/write-json.js";
import fs from "node:fs/promises";

/**
* Write custom files
*/
async function exportCustomFiles(dir, options, result) {
	const customFiles = options.customFiles || {};
	for (const filename in customFiles) {
		const content = customFiles[filename];
		if (content === null) {
			try {
				await fs.unlink(dir + "/" + filename);
			} catch {}
			continue;
		}
		if (typeof content === "string") await fs.writeFile(dir + "/" + filename, content, "utf8");
		else if (typeof content === "object") await writeJSONFile(dir + "/" + filename, content);
		result?.add(filename);
	}
}

export { exportCustomFiles };