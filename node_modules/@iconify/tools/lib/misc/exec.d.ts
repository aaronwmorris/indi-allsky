import { ExecOptions } from "node:child_process";
interface ExecResult {
  stdout: string;
  stderr: string;
}
/**
 * Exec as Promise
 */
declare function execAsync(cmd: string, options?: ExecOptions): Promise<ExecResult>;
export { ExecResult, execAsync };