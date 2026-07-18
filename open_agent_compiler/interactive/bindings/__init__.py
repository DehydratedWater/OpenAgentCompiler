"""Thin bindings that turn an InteractiveAgentSpec into a concrete runnable.

A binding is deliberately small and swappable — the framework commits to the
runtime-agnostic `InteractiveAgentSpec`, and each binding is a ~one-file
adapter to a specific interactive runtime. LangChain ships first; a raw-SDK
binding could follow. This keeps the framework from coupling its spine to any
one (churny) execution library.
"""
