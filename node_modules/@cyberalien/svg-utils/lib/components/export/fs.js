import { mkdir, writeFile } from "node:fs/promises";
/**
* Save exported files to filesystem
*/
async function saveExportedFilesToFS(files, dir) {
	let saved = 0;
	for (const { filename, content } of files) {
		const filePath = `${dir}/${filename}`;
		const dirPath = filePath.substring(0, filePath.lastIndexOf("/"));
		try {
			await mkdir(dirPath, { recursive: true });
		} catch {}
		await writeFile(filePath, content, "utf8");
		saved++;
	}
	return saved;
}
export { saveExportedFilesToFS };
