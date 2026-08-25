import os
import argparse
from datetime import datetime
from apoema_agent import run_apoema_pipeline
from apoema_flow import run_apoema_flow


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run APOEMA assessment analysis")
    parser.add_argument(
        "--exec-mode",
        type=str,
        choices=["crew", "flow"],
        default="flow",
        help="Execution mode: 'crew' for traditional Crew execution, 'flow' for Flow-based execution (default: flow)",
    )
    parser.add_argument(
        "--model",
        type=str,
        choices=["gemini"],
        default="gemini",
        help="Model provider to use (default: gemini)",
    )
    parser.add_argument(
        "--assessment-file",
        type=str,
        default="assessment_data.json",
        help="Path to the assessment data JSON file (default: assessment_data.json)",
    )
    parser.add_argument(
        "--pdf-file",
        type=str,
        default=None,
        help="Path to the PDF report file (optional)",
    )
    parser.add_argument(
        "--png-file",
        type=str,
        default=None,
        help="Path to the PNG plot image file (optional, alternative to PDF)",
    )
    parser.add_argument(
        "--csv-file",
        type=str,
        default=None,
        help="Path to the CSV data file (optional, used with PNG)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=datetime.now().strftime("%Y%m%d%H%M%S"),
        help="Prefix for output files (default: timestamp of execution)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        default=False,
        help="Ignore the checkpoint for this prefix and re-run all tasks (flow mode)",
    )

    args = parser.parse_args()
    return (
        args.exec_mode,
        args.model,
        args.assessment_file,
        args.pdf_file,
        args.png_file,
        args.csv_file,
        args.prefix,
        args.fresh,
    )


def main():
    """Main entry point."""
    (
        exec_mode,
        model,
        assessment_file,
        pdf_path,
        png_path,
        csv_path,
        output_prefix,
        fresh,
    ) = parse_arguments()

    print(f"\n🚀 APOEMA - Execution Mode: {exec_mode.upper()}")
    print(f"🤖 Model: {model.upper()}")

    # Display input information and validate
    has_pdf = pdf_path and os.path.exists(pdf_path)
    has_png_csv = png_path and os.path.exists(png_path) and csv_path and os.path.exists(csv_path)
    has_png_only = (
        png_path and os.path.exists(png_path) and (not csv_path or not os.path.exists(csv_path))
    )
    has_csv_only = (
        csv_path and os.path.exists(csv_path) and (not png_path or not os.path.exists(png_path))
    )

    if has_pdf:
        print(f"\n✓ Arquivo PDF carregado: {os.path.basename(pdf_path)}")
        print("✓ Tarefas de análise de relatório adicionadas ao pipeline\n")
    elif has_png_csv:
        print(f"\n✓ Imagem PNG carregada: {os.path.basename(png_path)}")
        print(f"✓ Dados CSV carregados: {os.path.basename(csv_path)}")
        print("✓ Tarefas de análise de gráfico PNG+CSV adicionadas ao pipeline\n")
    else:
        if has_png_only:
            print(
                f"⚠ Imagem PNG foi encontrada, mas arquivo CSV está faltando: {csv_path or 'não especificado'}"
            )
        if has_csv_only:
            print(
                f"⚠ Dados CSV foram encontrados, mas arquivo PNG está faltando: {png_path or 'não especificado'}"
            )
        if pdf_path and not has_pdf:
            print(f"⚠ Arquivo PDF não encontrado: {pdf_path}")
        print("\n💡 Opções:")
        print("   1. PDF: python main.py --model gemini --assessment-file <arquivo.json> --pdf-file <arquivo.pdf>")
        print(
            "   2. PNG+CSV: python main.py --model gemini --assessment-file <arquivo.json> --png-file <imagem.png> --csv-file <dados.csv>"
        )
        print("   3. Apenas assessment: python main.py --model gemini --assessment-file <arquivo.json>")
        print(
            "   4. Com prefixo customizado: python main.py --model gemini --assessment-file <arquivo.json> --prefix my_run"
        )

        print("\nExecutando apenas tarefas 1 e 2...\n")

    # Execute based on selected mode
    if exec_mode == "crew":
        # Traditional Crew execution
        run_apoema_pipeline(assessment_file, pdf_path, output_prefix, png_path, csv_path, model)
    else:
        # Flow-based execution
        run_apoema_flow(
            assessment_file,
            pdf_path,
            output_prefix,
            png_path,
            csv_path,
            model,
            fresh=fresh,
        )

    print("\n" + "=" * 80)
    print("EXECUÇÃO CONCLUÍDA")
    print("=" * 80)


if __name__ == "__main__":
    main()
