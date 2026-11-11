// @desc  Live check: a runaway loop is stopped by the budget. Run with budget_seconds=3.
// @writes false
long spins = 0;
while (true)
{
    ctx.Budget.Check();
    spins++;
}
