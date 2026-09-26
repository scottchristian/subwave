import { NextRequest } from "next/server";
export async function GET(req: NextRequest) {
  console.log("Incoming request from", req.headers.get("user-agent"));
  console.log("Range header:", req.headers.get("range"));
  console.log("Accept header:", req.headers.get("accept"));
}
