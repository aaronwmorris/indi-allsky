import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, normalize } from "pathe";
import { unzip as unzip$1 } from "fflate";

/**
* Unzip archive
*/
async function unzip(source, path, filter) {
	const dir = normalize(path);
	const data = await readFile(source);
	async function writeFiles(data) {
		const createdDirs = /* @__PURE__ */ new Set();
		for (const name in data) {
			const filePath = normalize(join(dir, name));
			if (filter && !filter(filePath)) continue;
			if (filePath.startsWith("/") || filePath.includes("../") || filePath.includes(":")) throw new Error("Invalid file path in zip: " + filePath);
			if (filePath.includes("/._")) continue;
			const isDir = filePath.endsWith("/");
			const fileDir = isDir ? filePath.slice(0, filePath.length - 1) : dirname(filePath);
			if (!createdDirs.has(fileDir)) {
				createdDirs.add(fileDir);
				try {
					await mkdir(fileDir, { recursive: true });
				} catch {}
			}
			if (!isDir) await writeFile(filePath, data[name]);
		}
	}
	return new Promise((resolve, reject) => {
		unzip$1(data, (err, unzipped) => {
			if (err) {
				reject(err);
				return;
			}
			writeFiles(unzipped).then(() => resolve()).catch((err) => reject(err));
		});
	});
}

export { unzip };