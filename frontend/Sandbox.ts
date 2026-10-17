// Standalone Daytona smoke test: `npx tsx Sandbox.ts`. The real detonator lives in backend/app/daytona_detonator.py.
import { Daytona } from '@daytona/sdk'
import 'dotenv/config'

const daytona = new Daytona({ apiKey: process.env.DAYTONA_API_KEY })
const sandbox = await daytona.create({ language: 'typescript' })
try {
  const response = await sandbox.process.codeRun('console.log("Hello World from code!")')
  console.log(response.result)
} finally {
  await sandbox.delete()
}
