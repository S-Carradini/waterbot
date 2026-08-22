"""L4 annotation: label pools, the scoring interface, and adjudication.

The only part of the judge system a human touches directly. Everything here is built around one
constraint - expert time is the binding resource - and one guarantee: annotators never see which
system produced an answer, or what any judge said about it.
"""
