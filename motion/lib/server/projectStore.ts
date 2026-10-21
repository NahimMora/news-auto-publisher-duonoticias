import { mkdir, readdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { projectSchema, type PieceInput, type Project } from "../../src/schema/piece";
import { INBOX_DIR, PROJECTS_DIR } from "./paths";

/**
 * Persistencia de proyectos. Interfaz desacoplada: hoy archivos JSON locales
 * (escritura atomica), manana una base de datos sin tocar el panel.
 */
export interface ProjectStore {
  list(): Promise<Project[]>;
  get(id: string): Promise<Project | null>;
  create(name: string, piece: PieceInput, origin?: Project["origin"]): Promise<Project>;
  update(id: string, patch: { name?: string; piece?: PieceInput }): Promise<Project | null>;
  remove(id: string): Promise<boolean>;
}

const safeId = (id: string) => /^[a-z0-9-]{6,64}$/i.test(id);

export class FileProjectStore implements ProjectStore {
  constructor(private readonly dir: string = PROJECTS_DIR) {}

  private file(id: string) {
    if (!safeId(id)) throw new Error("id de proyecto invalido");
    return path.join(this.dir, `${id}.json`);
  }

  private async write(project: Project) {
    await mkdir(this.dir, { recursive: true });
    const target = this.file(project.id);
    const tmp = `${target}.${process.pid}.tmp`;
    await writeFile(tmp, JSON.stringify(project, null, 2), "utf8");
    await rename(tmp, target);
  }

  async list(): Promise<Project[]> {
    await mkdir(this.dir, { recursive: true });
    const files = (await readdir(this.dir)).filter((f) => f.endsWith(".json"));
    const out: Project[] = [];
    for (const f of files) {
      try {
        const parsed = projectSchema.safeParse(JSON.parse(await readFile(path.join(this.dir, f), "utf8")));
        if (parsed.success) out.push(parsed.data);
      } catch {
        // archivo corrupto: se ignora en el listado
      }
    }
    return out.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  async get(id: string): Promise<Project | null> {
    try {
      const parsed = projectSchema.safeParse(JSON.parse(await readFile(this.file(id), "utf8")));
      return parsed.success ? parsed.data : null;
    } catch {
      return null;
    }
  }

  async create(name: string, piece: PieceInput, origin: Project["origin"] = "manual"): Promise<Project> {
    const now = new Date().toISOString();
    const id = `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    const project = projectSchema.parse({ id, name, piece, createdAt: now, updatedAt: now, origin });
    await this.write(project);
    return project;
  }

  async update(id: string, patch: { name?: string; piece?: PieceInput }): Promise<Project | null> {
    const current = await this.get(id);
    if (!current) return null;
    const next = projectSchema.parse({
      ...current,
      name: patch.name ?? current.name,
      piece: patch.piece ?? current.piece,
      updatedAt: new Date().toISOString(),
    });
    await this.write(next);
    return next;
  }

  async remove(id: string): Promise<boolean> {
    try {
      await rm(this.file(id));
      return true;
    } catch {
      return false;
    }
  }
}

export const projectStore: ProjectStore = new FileProjectStore();

/** Piezas que dejo el pipeline para revision editorial. */
export const listInbox = async (): Promise<Array<{ file: string; piece: PieceInput; receivedAt: string }>> => {
  await mkdir(INBOX_DIR, { recursive: true });
  const files = (await readdir(INBOX_DIR)).filter((f) => f.endsWith(".json")).sort().reverse().slice(0, 60);
  const out: Array<{ file: string; piece: PieceInput; receivedAt: string }> = [];
  for (const f of files) {
    try {
      const raw = JSON.parse(await readFile(path.join(INBOX_DIR, f), "utf8"));
      out.push({ file: f, piece: raw.piece ?? raw, receivedAt: raw.receivedAt ?? "" });
    } catch {
      // ignorado
    }
  }
  return out;
};
