import os
import sys
import time
import argparse
from typing import List, Dict, Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.live import Live

from llm_indexer.config import LLM_MODEL, EMBEDDING_MODEL
from llm_indexer.ollama_client import OllamaClient
from llm_indexer.parser import CodebaseParser
from llm_indexer.chunker import CodebaseChunker
from llm_indexer.store import CodebaseVectorStore

console = Console()

def format_context_snippets(results: List[Dict[str, Any]]) -> str:
    """
    Format search results into a clean text block for the LLM system prompt.
    """
    formatted = []
    for idx, res in enumerate(results, 1):
        meta = res["metadata"]
        header = f"Snippet #{idx} | File: {meta.get('relative_path')} | Lines: {meta.get('start_line')}-{meta.get('end_line')} | Lang: {meta.get('language')}"
        separator = "=" * len(header)
        formatted.append(f"{header}\n{separator}\n{res['content']}\n{separator}\n")
    return "\n".join(formatted)

def handle_index(args):
    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        console.print(f"[red]Error: Path '{path}' does not exist.[/red]")
        sys.exit(1)
        
    collection_name = args.name or os.path.basename(path.rstrip(os.sep))
    if not collection_name:
        collection_name = "default_codebase"
        
    console.print(Panel(
        f"[bold blue]Indexing Codebase[/bold blue]\n"
        f"Source: [cyan]{path}[/cyan]\n"
        f"Collection/DB Name: [cyan]{collection_name}[/cyan]\n"
        f"Embedding Model: [cyan]{EMBEDDING_MODEL}[/cyan]",
        expand=False
    ))
    
    start_time = time.time()
    
    # 1. Scan files
    parser = CodebaseParser(path)
    with console.status("[bold green]Scanning codebase directory...", spinner="dots") as status:
        files = parser.scan_files()
        
    if not files:
        console.print("[yellow]No supported code files found in the directory.[/yellow]")
        return
        
    console.print(f"Scanned [green]{len(files)}[/green] files successfully.")
    
    # 2. Chunk files
    chunker = CodebaseChunker()
    all_chunks = []
    with console.status("[bold green]Chunking files...", spinner="dots"):
        for f in files:
            chunks = chunker.chunk_file(f)
            all_chunks.extend(chunks)
            
    if not all_chunks:
        console.print("[yellow]No text chunks generated. Files might be empty.[/yellow]")
        return
        
    console.print(f"Created [green]{len(all_chunks)}[/green] text chunks.")
    
    # 3. Generate embeddings and store
    store = CodebaseVectorStore()
    client = OllamaClient()
    
    # We clear the existing collection first if requested or just overwrite
    # Chroma handles duplicate IDs by overwriting/upserting, but it's cleaner to overwrite
    if args.overwrite:
        store.delete_collection(collection_name)
        console.print(f"Deleted old collection '{collection_name}' for clean overwrite.")
        
    embeddings = []
    
    # Run embedding with a progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Generating embeddings & storing...", total=len(all_chunks))
        
        batch_size = 64
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            batch_texts = [c["content"] for c in batch]
            
            # Generate embeddings
            batch_embeddings = client.embed(batch_texts)
            
            # Save to store
            store.add_chunks(collection_name, batch, batch_embeddings)
            
            progress.update(task, advance=len(batch))
            
    elapsed = time.time() - start_time
    
    # Print summary table
    summary_table = Table(title="Indexing Summary", show_header=True, header_style="bold magenta")
    summary_table.add_column("Metric", style="dim", width=25)
    summary_table.add_column("Value", style="cyan")
    
    summary_table.add_row("Total Files Indexed", str(len(files)))
    summary_table.add_row("Total Chunks Created", str(len(all_chunks)))
    summary_table.add_row("Vector DB Name", collection_name)
    summary_table.add_row("Time Taken (s)", f"{elapsed:.2f}")
    
    console.print(summary_table)
    console.print("[bold green]✓ Codebase successfully indexed![/bold green]")

def handle_query(args):
    collection_name = args.name
    if not collection_name:
        console.print("[red]Error: Please specify the codebase collection name using --name.[/red]")
        sys.exit(1)
        
    store = CodebaseVectorStore()
    client = OllamaClient()
    
    # Verify collection exists and has documents
    count = store.get_collection_count(collection_name)
    if count == 0:
        console.print(f"[red]Error: Collection '{collection_name}' is empty or does not exist. Index the codebase first.[/red]")
        sys.exit(1)
        
    console.print(f"[dim]Searching codebase '{collection_name}' using query embeddings...[/dim]")
    
    # 1. Embed query
    query_embeddings = client.embed([args.question])
    if not query_embeddings:
        console.print("[red]Error generating embedding for the query.[/red]")
        sys.exit(1)
        
    # 2. Retrieve relevant chunks
    results = store.query(collection_name, query_embeddings[0], n_results=args.num_results)
    if not results:
        console.print("[yellow]No relevant context found in codebase.[/yellow]")
        return
        
    # Show references
    console.print("\n[bold yellow]Retrieved Reference Snippets:[/bold yellow]")
    for idx, res in enumerate(results, 1):
        meta = res["metadata"]
        console.print(f" [bold cyan][{idx}][/bold cyan] {meta['relative_path']}:{meta['start_line']}-{meta['end_line']} (Score: {1 - res['distance']:.3f})")
        
    console.print(f"\n[bold green]Answer from {LLM_MODEL}:[/bold green]\n")
    
    # 3. Augment Prompt and Chat
    context_str = format_context_snippets(results)
    system_prompt = (
        f"You are an expert software engineer assistant specializing in code explanation, debugging, and architecture design.\n"
        f"You are helping the user understand a codebase called '{collection_name}'.\n"
        f"Below are relevant code snippets retrieved from the codebase for context. Use these snippets to answer the user's question.\n"
        f"Refer to specific files and line numbers where appropriate.\n"
        f"Keep your answers accurate, clear, and well-structured.\n\n"
        f"Context:\n{context_str}"
    )
    
    # Stream the output
    for chunk in client.chat_stream(system_prompt, args.question):
        print(chunk, end="", flush=True)
    print("\n")

def handle_chat(args):
    collection_name = args.name
    if not collection_name:
        console.print("[red]Error: Please specify the codebase collection name using --name.[/red]")
        sys.exit(1)
        
    store = CodebaseVectorStore()
    client = OllamaClient()
    
    count = store.get_collection_count(collection_name)
    if count == 0:
        console.print(f"[red]Error: Collection '{collection_name}' is empty or does not exist. Index the codebase first.[/red]")
        sys.exit(1)
        
    console.print(Panel(
        f"[bold green]Interactive Chat Session[/bold green]\n"
        f"Codebase: [cyan]{collection_name}[/cyan] ({count} chunks)\n"
        f"LLM: [cyan]{LLM_MODEL}[/cyan]\n"
        f"Type [yellow]exit[/yellow] or [yellow]quit[/yellow] to end.",
        expand=False
    ))
    
    while True:
        try:
            question = console.input("\n[bold magenta]You > [/bold magenta]")
            if question.strip().lower() in ("exit", "quit"):
                console.print("[cyan]Goodbye![/cyan]")
                break
                
            if not question.strip():
                continue
                
            # 1. Embed query
            with console.status("[dim]Searching codebase...", spinner="dots"):
                query_embeddings = client.embed([question])
                if not query_embeddings:
                    console.print("[red]Error generating embedding.[/red]")
                    continue
                results = store.query(collection_name, query_embeddings[0], n_results=args.num_results)
                
            if not results:
                console.print("[yellow]No relevant context found.[/yellow]")
                continue
                
            # Show brief references
            ref_names = []
            for res in results:
                meta = res["metadata"]
                ref_names.append(f"{meta['file_name']}:{meta['start_line']}-{meta['end_line']}")
            console.print(f"[dim]Context loaded from: {', '.join(ref_names)}[/dim]")
            
            console.print(f"\n[bold green]Assistant > [/bold green]")
            
            # Chat completion
            context_str = format_context_snippets(results)
            system_prompt = (
                f"You are an expert software engineer assistant specializing in code explanation, debugging, and architecture design.\n"
                f"You are helping the user understand a codebase called '{collection_name}'.\n"
                f"Below are relevant code snippets retrieved from the codebase for context. Use these snippets to answer the user's question.\n"
                f"Refer to specific files and line numbers where appropriate.\n\n"
                f"Context:\n{context_str}"
            )
            
            for chunk in client.chat_stream(system_prompt, question):
                print(chunk, end="", flush=True)
            print()
            
        except KeyboardInterrupt:
            console.print("\n[cyan]Session ended via keyboard interrupt.[/cyan]")
            break

def main():
    parser = argparse.ArgumentParser(
        description="Local LLM-powered Codebase Indexer and Q&A Assistant"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")
    
    # Index parser
    index_parser = subparsers.add_parser("index", help="Index a codebase directory")
    index_parser.add_argument("path", type=str, help="Path to codebase directory")
    index_parser.add_argument("--name", type=str, help="Custom name for vector database collection")
    index_parser.add_argument("--overwrite", action="store_true", help="Delete existing database index for this codebase and build fresh")
    
    # Query parser
    query_parser = subparsers.add_parser("query", help="Ask a question about an indexed codebase")
    query_parser.add_argument("question", type=str, help="The question to ask")
    query_parser.add_argument("--name", type=str, help="Codebase collection name")
    query_parser.add_argument("--num-results", type=int, default=5, help="Number of code snippets to retrieve as context")
    
    # Chat parser
    chat_parser = subparsers.add_parser("chat", help="Start an interactive Q&A session")
    chat_parser.add_argument("--name", type=str, help="Codebase collection name")
    chat_parser.add_argument("--num-results", type=int, default=5, help="Number of code snippets to retrieve as context")
    
    args = parser.parse_args()
    
    if args.command == "index":
        handle_index(args)
    elif args.command == "query":
        handle_query(args)
    elif args.command == "chat":
        handle_chat(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
