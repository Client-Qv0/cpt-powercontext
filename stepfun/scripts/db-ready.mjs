import { databaseClient } from "../server/store.mjs";
const client = databaseClient();
let ready = false;
for (let i = 0; i < 60; i++) {
  try {
    const result = await client.execute("SELECT VERSION() AS version");
    console.log(result[0].version);
    ready = true;
    break;
  } catch {
    console.log("等待 seekdb 启动…");
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}
await client.close();
if (!ready) {
  console.error("seekdb 未就绪，请检查 docker compose logs");
  process.exitCode = 1;
}
